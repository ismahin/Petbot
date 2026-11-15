"""Validate incremental decoding against the installed model's real decoder."""
import importlib.util
import json
from pathlib import Path
import unittest
import torch
from mithi_cached_writer import enable_cached_writer


class CachedWriterTest(unittest.TestCase):
    def test_real_weights_match_full_prefix_and_reset(self):
        torch.set_num_threads(2)
        root = Path(__file__).resolve().parent
        folder = Path(json.loads((root/'mithi-model-source.json').read_text())['model_dir'])
        spec = importlib.util.spec_from_file_location('test_mithi_run', folder/'run.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        model = module.Mithi(str(folder), device='cpu')
        writer = model.writer
        original = writer.write
        torch.manual_seed(72)
        memory = torch.randn(1, 12, writer.d)
        enc_pad = torch.zeros(1, 12, dtype=torch.bool)
        ids = torch.randint(1, 100, (1, 12))
        positions = torch.arange(12)[None]
        context = torch.zeros(1, 12, 13, dtype=torch.long)
        context[..., 0] = torch.randint(0, 20, (1, 12))
        with torch.inference_mode():
            expected = [original(memory, enc_pad, ids[:, :n], positions[:, :n],
                context[:, :n], torch.zeros(1, n, dtype=torch.bool))[:, -1:]
                for n in range(1, 13)]
            enable_cached_writer(model)
            for n in range(1, 13):
                actual = writer.write(memory, enc_pad, ids[:, :n], positions[:, :n],
                    context[:, :n], torch.zeros(1, n, dtype=torch.bool))
                torch.testing.assert_close(actual, expected[n-1], atol=2e-5, rtol=2e-5)
            actual = writer.write(memory, enc_pad, ids[:, :1], positions[:, :1],
                context[:, :1], torch.zeros(1, 1, dtype=torch.bool))
            torch.testing.assert_close(actual, expected[0], atol=2e-5, rtol=2e-5)
            # A discontinuous prefix takes the original guarded route.
            actual = writer.write(memory, enc_pad, ids[:, :4], positions[:, :4],
                context[:, :4], torch.zeros(1, 4, dtype=torch.bool))
            torch.testing.assert_close(actual[:, -1:], expected[3], atol=2e-5, rtol=2e-5)


if __name__ == '__main__':
    unittest.main()
