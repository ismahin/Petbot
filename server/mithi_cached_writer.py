"""Incremental KV evaluation of Mithi's autoregressive prosody decoder.

Weights, phonemes, sampling and acoustic decoder are unchanged. Only past
transformer projections are reused. The stock writer recomputes the whole
causal prefix for every phoneme; it is retained as a guarded fallback.
"""
import types
import torch
import torch.nn.functional as F


def enable_cached_writer(model):
    writer = model.writer
    if getattr(writer, '_deskter_cached', False):
        return
    original = writer.write
    layers = writer.dec.layers
    for layer in layers:
        if not layer.norm_first or not layer.self_attn.batch_first:
            raise ValueError('Unsupported Mithi decoder layout')
        for attention in (layer.self_attn, layer.multihead_attn):
            if not attention._qkv_same_embed_dim or attention.bias_k is not None or attention.bias_v is not None or attention.add_zero_attn:
                raise ValueError('Unsupported Mithi attention layout')
    state = {}

    def heads(tensor, attention):
        batch, length, width = tensor.shape
        return tensor.view(batch, length, attention.num_heads, width // attention.num_heads).transpose(1, 2)

    def project(tensor, attention, begin, end):
        bias = attention.in_proj_bias
        return F.linear(tensor, attention.in_proj_weight[begin:end], None if bias is None else bias[begin:end])

    def attend(query, keys, values, attention):
        result = F.scaled_dot_product_attention(heads(query, attention), keys, values, dropout_p=0.0)
        result = result.transpose(1, 2).contiguous().view(query.shape)
        return F.linear(result, attention.out_proj.weight, attention.out_proj.bias)

    def write(self, H, enc_pad, dec_ids, dec_map, ctx, dec_pad):
        length = dec_ids.shape[1]
        if self.training or torch.is_grad_enabled() or H.shape[0] != 1 or bool(enc_pad.any()) or bool(dec_pad.any()):
            state.clear()
            return original(H, enc_pad, dec_ids, dec_map, ctx, dec_pad)
        if length == 1:
            state.clear()
            state.update(memory=H.data_ptr(), length=0, layers=[{} for _ in layers])
        if state.get('memory') != H.data_ptr() or state.get('length') != length - 1:
            state.clear()
            return original(H, enc_pad, dec_ids, dec_map, ctx, dec_pad)
        previous = self.start.view(1, 1, -1) if length == 1 else sum(
            embedding(ctx[:, -2:-1, k]) for k, embedding in enumerate(self.code_emb))
        x = torch.gather(H, 1, dec_map[:, -1:, None].expand(-1, -1, self.d)) + self.tok(dec_ids[:, -1:]) + previous
        for layer, cache in zip(layers, state['layers']):
            attention = layer.self_attn
            width = attention.embed_dim
            normalized = layer.norm1(x)
            q, k, v = project(normalized, attention, 0, 3 * width).chunk(3, dim=-1)
            k, v = heads(k, attention), heads(v, attention)
            if 'key' in cache:
                k = torch.cat((cache['key'], k), dim=2)
                v = torch.cat((cache['value'], v), dim=2)
            cache.update(key=k, value=v)
            x = x + layer.dropout1(attend(q, k, v, attention))
            attention = layer.multihead_attn
            q = project(layer.norm2(x), attention, 0, width)
            if 'memory_key' not in cache:
                k, v = project(H, attention, width, 3 * width).chunk(2, dim=-1)
                cache.update(memory_key=heads(k, attention), memory_value=heads(v, attention))
            x = x + layer.dropout2(attend(q, cache['memory_key'], cache['memory_value'], attention))
            normalized = layer.norm3(x)
            x = x + layer.dropout3(layer.linear2(layer.dropout(layer.activation(layer.linear1(normalized)))))
        if self.dec.norm is not None:
            x = self.dec.norm(x)
        state['length'] = length
        # The model's sampler reads only the final timestep. Return that same
        # three-dimensional shape with length one, avoiding unused prefix work.
        return self.dec_norm(x)

    writer.write = types.MethodType(write, writer)
    writer._deskter_cached = True
