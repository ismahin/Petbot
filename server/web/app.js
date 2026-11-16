'use strict';
let saved, revision, voices = [], previewUrl, previewing = false, saving = false, cloudMode = false, pollTimer;
const $ = id => document.getElementById(id);
const numeric = new Set(['speech_volume','temperature','groq_max_tokens','first_phrase_words','following_phrase_words','silence_ms','max_utterance_seconds','vad_mode','output_bitrate','playback_prefill_frames']);
const pages = {
 overview: ['A little companion.<br>A personality of your own.', 'Shape how Deskter thinks, speaks, and listens.'],
 personality: ['A personality, made personal.', 'Set the instructions that shape every reply.'],
 voices: ['Find Deskter’s voice.', 'Ten Mithi voices. One that feels right for you.'],
 conversation: ['Good conversations start here.', 'Tune the balance between thoughtful replies and a quick response.'],
 history: ['Every conversation, made clear.', 'See the words Deskter recognized, the reply it generated, and what reached playback.'],
 devices: ['A home for every device.', 'Create API keys, connect your ESP boards, and manage access.'],
 audio: ['A smoother back-and-forth.', 'Fine-tune playback, listening, and the pauses in between.']
};
function page(name) {
 if (!pages[name]) name = 'overview';
 document.querySelectorAll('[data-section]').forEach(el => el.hidden = el.dataset.section !== name);
 document.querySelectorAll('[data-page]').forEach(el => { el.classList.toggle('active', el.dataset.page === name); if(el.dataset.page === name) el.setAttribute('aria-current','page'); else el.removeAttribute('aria-current'); });
 $('page-title').innerHTML = pages[name][0]; $('page-description').textContent = pages[name][1];
 if(name==='history' && cloudMode) refreshHistory();
 $('crumb').textContent = document.querySelector(`[data-page="${name}"]`).textContent.replace('10','').replace(/[◉✧≋☷◷]/g,'').trim();
}
function notify(text, error=false) { const el=$('toast'); el.textContent=text; el.classList.toggle('error',error); el.hidden=false; clearTimeout(notify.timer); notify.timer=setTimeout(()=>el.hidden=true,6500); }
async function api(path, options={}) {
 const response=await fetch('/api/'+path,{...options,headers:{'Content-Type':'application/json','X-Deskter-Panel':'1',...options.headers}});
 if(!response.ok){let text='Request failed. Please try again.';try{const data=await response.json();text=typeof data.detail==='string'?data.detail:'Some settings are outside the allowed range. Check your entries.';}catch{}const error=new Error(text);error.status=response.status;throw error;}
 return response;
}
function values(){const data={...saved};for(const key of Object.keys(saved)){const el=$(key);if(!el)continue;data[key]=el.type==='checkbox'?el.checked:numeric.has(key)?Number(el.value):el.value;}return data;}
function changed(){if(!saved)return;const data=values();const dirty=JSON.stringify(data)!==JSON.stringify(saved);$('save').disabled=!dirty||saving;$('discard').disabled=!dirty||saving;$('save-state').textContent=saving?'Saving…':dirty?'You have unsaved changes':'All changes saved';$('save-description').textContent=dirty?'Save to apply your settings to Deskter.':'Your companion, configured on your PC.';$('prompt-count').textContent=$('system_prompt').value.length.toLocaleString()+' / 16,000';document.querySelectorAll('[data-output]').forEach(el=>el.textContent=data[el.dataset.output]+(el.dataset.output==='speech_volume'?'%':''));}
let selectedVoice='malini';
function renderVoices(){const grid=$('voice-grid');grid.replaceChildren();voices.forEach(name=>{const card=document.createElement('article');card.className='voice-card'+(name===selectedVoice?' selected':'');const avatar=document.createElement('div');avatar.className='voice-avatar';avatar.textContent=name[0].toUpperCase();const check=document.createElement('span');check.className='voice-check';check.textContent=name===selectedVoice?'✓ Selected':'';const title=document.createElement('h3');title.textContent=name;const sub=document.createElement('p');sub.textContent='Bangla · English · Mixed';const actions=document.createElement('div');actions.className='voice-actions';const listen=document.createElement('button');listen.textContent='▶ Listen';listen.disabled=previewing;listen.setAttribute('aria-label','Preview '+name);listen.onclick=()=>preview(name);const choose=document.createElement('button');choose.className='choose';choose.textContent=name===selectedVoice?'Selected':'Select voice';choose.setAttribute('aria-pressed',String(name===selectedVoice));choose.onclick=()=>{selectedVoice=name;savedDraftVoice();renderVoices();changed();};actions.append(listen,choose);card.append(avatar,check,title,sub,actions);grid.append(card);});}
// Keep the selected voice as a normal form field so it participates in draft/save.
const voiceField=document.createElement('input');voiceField.id='mithi_voice';voiceField.type='hidden';document.body.append(voiceField);
function savedDraftVoice(){voiceField.value=selectedVoice;}
function populate(){for(const [key,value] of Object.entries(saved)){const el=$(key);if(!el)continue;if(el.type==='checkbox')el.checked=value;else el.value=value;}selectedVoice=saved.mithi_voice;renderVoices();changed();}
async function preview(name){if(previewing)return;const text=$('preview-text').value.trim();if(!text)return notify('Enter a sentence to preview.',true);previewing=true;renderVoices();$('preview-status').textContent='Generating '+name+'…';$('preview-audio').pause();try{const response=await api('preview',{method:'POST',body:JSON.stringify({voice:name,text})});if(previewUrl)URL.revokeObjectURL(previewUrl);previewUrl=URL.createObjectURL(await response.blob());$('preview-audio').src=previewUrl;$('preview-audio').hidden=false;$('preview-status').textContent=name[0].toUpperCase()+name.slice(1)+' · PC speaker preview';await $('preview-audio').play();}catch(error){$('preview-status').textContent='Preview unavailable';notify(error.message,true);}finally{previewing=false;renderVoices();}}
async function refreshStatus(){try{const s=await(await api('status')).json();$('server-badge').textContent=s.ready?'Server online':'Starting up';$('robot-status').textContent=s.busy?'In conversation':s.device_connected?'Connected':'Waiting for Deskter';$('robot-detail').textContent=s.device_connected?'XIAO ESP32S3 Sense':'Wake your robot to connect';if(s.cloud){$('robot-status').textContent='Cloud endpoint ready';$('robot-detail').textContent='Live connection counts are not tracked';}$('current-voice').textContent=s.voice[0].toUpperCase()+s.voice.slice(1);$('current-provider').textContent='Groq Cloud';$('current-model').textContent=s.model;}catch{$('server-badge').textContent='Server unavailable';$('robot-status').textContent='Unavailable';$('robot-detail').textContent='Check that the server is running';}}
document.querySelectorAll('[data-page]').forEach(el=>el.onclick=()=>location.hash=el.dataset.page);
document.querySelectorAll('[data-go]').forEach(el=>el.onclick=()=>location.hash=el.dataset.go);
window.addEventListener('hashchange',()=>page(location.hash.slice(1)));
document.querySelectorAll('input,select,textarea').forEach(el=>{if(el.id!=='preview-text'){el.addEventListener('input',changed);el.addEventListener('change',changed);}});
$('sample-bn').onclick=()=>{$('preview-text').value='হ্যালো মাহিন, আমি ডেস্কটার। আজ তোমার দিনটা কেমন গেল?';};
$('sample-en').onclick=()=>{$('preview-text').value='Hello Mahin, I am Deskter. How has your day been? I am here to listen.';};
$('discard').onclick=()=>{if(!confirm('Discard your unsaved changes?'))return;populate();notify('Draft changes discarded.');};
$('save').onclick=async()=>{const data=values();if(!data.system_prompt.trim())return notify('Please enter a system prompt.',true);for(const key of Object.keys(data)){const el=$(key);if(el&&!el.checkValidity()){location.hash=el.closest('[data-section]')?.dataset.section||'personality';setTimeout(()=>el.reportValidity(),0);return;}}saving=true;changed();try{const result=await(await api('settings',{method:'PUT',body:JSON.stringify({revision,settings:data})})).json();saved=data;revision=result.revision;notify(result.message);refreshStatus();}catch(error){notify(error.message,true);}finally{saving=false;changed();}};
window.addEventListener('beforeunload',event=>{if(saved&&JSON.stringify(values())!==JSON.stringify(saved)){event.preventDefault();event.returnValue='';}});
async function loadDevices(){try{const data=await(await api('devices')).json();const list=$('device-list');list.replaceChildren();for(const device of data.devices){const row=document.createElement('div');row.className='device-row';const label=document.createElement('div');label.textContent=device.name;const sub=document.createElement('small');sub.textContent='Key fingerprint: '+device.fingerprint;label.append(sub);const button=document.createElement('button');button.className='secondary';button.textContent='Revoke';button.onclick=async()=>{if(!confirm('Revoke this device key? The device will need a new key to reconnect.'))return;try{await api('devices/'+device.id,{method:'DELETE'});notify('Device key revoked.');await loadDevices();}catch(error){notify(error.message,true);}};row.append(label,button);list.append(row);}}catch(error){$('device-error').textContent=error.message;}}
$('create-device').onclick=async()=>{const name=$('device-name').value.trim();if(!name)return notify('Enter a device name.',true);$('create-device').disabled=true;try{const data=await(await api('devices',{method:'POST',body:JSON.stringify({name})})).json();$('new-device-key').value=data.api_key;$('new-device').hidden=false;await loadDevices();}catch(error){notify(error.message,true);}finally{$('create-device').disabled=false;}};
$('dismiss-key').onclick=()=>{$('new-device-key').value='';$('new-device').hidden=true;};
$('login-form').onsubmit=async event=>{event.preventDefault();$('login-submit').disabled=true;try{await api('login',{method:'POST',body:JSON.stringify({key:$('admin-key').value})});$('admin-key').value='';$('login-screen').hidden=true;await init();}catch(error){$('login-error').textContent=error.message;}finally{$('login-submit').disabled=false;}};
async function init(){page(location.hash.slice(1));try{const data=await(await api('settings')).json();saved=data.settings;revision=data.revision;voices=data.voices;cloudMode=!!data.cloud;populate();$('load-error').hidden=true;if(cloudMode){$('transcript-row').hidden=true;$('history-nav').hidden=false;$('asr-settings').hidden=false;$('devices-nav').hidden=false;$('api-base').value=location.origin+'/api/v1';$('preview-status').textContent='Cold first previews can take longer. Mithi loads on demand.';if(!data.storage_ready)notify('Connect PostgreSQL or Redis storage to save settings and create device keys.',true);else await loadDevices();}$('login-screen').hidden=true;await refreshStatus();clearInterval(pollTimer);pollTimer=setInterval(refreshStatus,cloudMode?30000:5000);if(cloudMode){refreshHistory();clearInterval(historyTimer);historyTimer=setInterval(()=>{if(location.hash==='#history'&&!document.hidden)refreshHistory();},3000);}}catch(error){if(error.status===401){$('login-screen').hidden=false;return;}$('load-error').textContent='Could not load Deskter settings. '+error.message;$('load-error').hidden=false;}}
init();

let historyTimer, historyBusy=false, historyRows=[];
const historyCards=new Map();
function node(tag,text,cls){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;}
function turnCard(turn){
 const card=node('article',undefined,'card turn-card');card.dataset.turn=turn.id;
 const top=node('div',undefined,'history-heading');const title=node('div');title.append(node('strong',turn.source==='browser'?'PC microphone test':'Robot conversation'),node('p',new Date(turn.created*1000).toLocaleString()));top.append(title,node('span',turn.status.replaceAll('_',' '),'turn-status'));card.append(top);
 const field=(title,text)=>{const block=node('div',undefined,'turn-field');block.append(node('small',title),node('p',text||'Waiting...'));card.append(block);};
 field('1. Recognized speech / input to LLM',turn.heard|| (turn.status==='no_speech'?'No reliable speech detected.':''));
 if(turn.source!=='browser'){
  field('2. '+(turn.response_source==='llm'?'LLM reply':'Reply'),turn.llm_output);
  field('3. Text sent for speech',turn.speech_text?.join(' '));
  const ack=turn.playback||{};let playback='No speech audio sent.';
  if(ack.state==='streaming')playback='Sending speech audio to the device...';
  if(ack.state==='sent')playback='Audio sent; waiting for device playback acknowledgement.';
  if(['complete','partial','error'].includes(ack.state))playback='Device playback '+ack.state+' - '+(ack.packets||0)+' packets, '+(ack.errors||0)+' errors, '+(ack.drops||0)+' dropped frames, '+(ack.underruns||0)+' underruns.';
  card.append(node('p',playback,'turn-playback'));
 }
 if(turn.error)card.append(node('p',turn.error,'notice error'));
 if(turn.storage_warning)card.append(node('p',turn.storage_warning,'notice'));
 const metrics=turn.metrics||{},asr=turn.asr||{},timing=turn.timing||{};
 const info=[];if(metrics.seconds!==undefined)info.push(metrics.seconds+' s input');if(metrics.rms_dbfs!==undefined)info.push(metrics.rms_dbfs+' dBFS signal');if(metrics.gain!==undefined)info.push(metrics.gain+'x gain');if(metrics.clipping_percent)info.push(metrics.clipping_percent+'% clipping');if(asr.model)info.push(asr.model);if(asr.language)info.push(asr.language);if(timing.asr_seconds!==undefined)info.push('STT '+timing.asr_seconds+' s');card.append(node('p',info.join(' / '),'hint'));
 const audioRow=node('div',undefined,'turn-audio');
 for(const kind of ['input','output'])if(turn.audio?.[kind]){const part=node('div');const meta=turn.audio[kind];part.append(node('label',kind==='input'?'Audio sent to recognition':'Generated speech sample'));const audio=document.createElement('audio');audio.controls=true;audio.preload='none';audio.onerror=()=>notify('This audio sample expired or is unavailable. Refresh the log.',true);audio.src='/api/conversations/'+encodeURIComponent(turn.id)+'/audio/'+kind;part.append(audio,node('small',meta.seconds+' s'+(meta.truncated?' (shortened sample)':'')));audioRow.append(part);}
 card.append(audioRow);
 const details=node('details');details.append(node('summary','Exact LLM messages and recognition metadata'));details.append(node('pre',JSON.stringify({llm_input:turn.llm_input,asr:turn.asr,metrics:turn.metrics,timing:turn.timing,comparisons:turn.comparisons||[]},null,2)));card.append(details);
 if(turn.audio?.input){const retry=node('button','Recheck STT with selected recognition settings','secondary');retry.onclick=async()=>{retry.disabled=true;try{const result=await(await api('conversations/'+encodeURIComponent(turn.id)+'/retry-asr',{method:'POST',body:JSON.stringify({model:$('asr_model').value||'whisper-large-v3',language:$('asr_language').value||'auto'})})).json();notify('Recheck: '+(result.text||'No reliable speech detected.'));await refreshHistory();}catch(error){notify(error.message,true);}finally{retry.disabled=false;}};card.append(retry);}
 return card;
}
async function refreshHistory(){
 if(!cloudMode||historyBusy)return;historyBusy=true;
 try{const data=await(await api('conversations')).json();historyRows=data.turns;const seen=new Set();$('history-storage').textContent=(data.storage==='postgresql'?'PostgreSQL - shared history. ':'Temporary history on this instance only. ')+data.retention;$('history-empty').hidden=!!data.turns.length;
  const list=$('history-list');for(const turn of data.turns){seen.add(turn.id);const signature=JSON.stringify(turn);let item=historyCards.get(turn.id);const isPlaying=[...(item?.element.querySelectorAll('audio')||[])].some(a=>!a.paused);if(!item|| (item.signature!==signature&&!isPlaying)){const el=turnCard(turn);if(item){const wasOpen=item.element.querySelector('details')?.open;item.element.replaceWith(el);if(wasOpen)el.querySelector('details').open=true;}else list.append(el);item={signature,element:el};historyCards.set(turn.id,item);}}
  // Reorder newest first without replacing stable cards or interrupting audio.
  let position=list.firstElementChild;for(const turn of data.turns){const el=historyCards.get(turn.id).element;if(el!==position)list.insertBefore(el,position);position=el.nextElementSibling;}
  for(const [id,item]of historyCards)if(!seen.has(id)){item.element.remove();historyCards.delete(id);}$('history-error').hidden=true;
 }catch(error){$('history-error').textContent=error.message;$('history-error').hidden=false;}finally{historyBusy=false;}
}
$('refresh-history').onclick=refreshHistory;
$('clear-history').onclick=async()=>{if(!confirm('Delete the retained conversation log and diagnostic audio?'))return;try{await api('conversations',{method:'DELETE'});await refreshHistory();notify('Conversation log cleared.');}catch(error){notify(error.message,true);}};
$('export-history').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(historyRows,null,2)],{type:'application/json'}));const link=node('a');link.href=url;link.download='deskter-conversations.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
let recording;
$('record-test').onclick=async()=>{
 try{if(!navigator.mediaDevices?.getUserMedia)throw new Error('Microphone recording needs HTTPS and a supported browser.');const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true}});const context=new AudioContext();await context.resume();const source=context.createMediaStreamSource(stream);const processor=context.createScriptProcessor(4096,1,1),mute=context.createGain();mute.gain.value=0;const chunks=[];let total=0;processor.onaudioprocess=e=>{if(!recording)return;const x=new Float32Array(e.inputBuffer.getChannelData(0));chunks.push(x);total+=x.length;};source.connect(processor);processor.connect(mute);mute.connect(context.destination);recording={stream,context,source,processor,mute,chunks,get total(){return total;}};$('record-test').disabled=true;$('stop-test').hidden=false;$('record-status').textContent='Recording. Say a sentence, then press Stop.';recording.timer=setTimeout(()=>$('stop-test').click(),20000);
 }catch(error){$('record-status').textContent=error.message;}
};
$('stop-test').onclick=async()=>{
 const r=recording;if(!r)return;recording=null;clearTimeout(r.timer);$('stop-test').hidden=true;
 try{r.processor.disconnect();r.source.disconnect();r.mute.disconnect();r.stream.getTracks().forEach(t=>t.stop());const rate=r.context.sampleRate;await r.context.close();const input=new Float32Array(r.total);let offset=0;for(const chunk of r.chunks){input.set(chunk,offset);offset+=chunk.length;}if(input.length<rate*.1)throw new Error('Please record at least a short sentence.');const offline=new OfflineAudioContext(1,Math.ceil(input.length*16000/rate),16000);const buffer=offline.createBuffer(1,input.length,rate);buffer.copyToChannel(input,0);const src=offline.createBufferSource();src.buffer=buffer;src.connect(offline.destination);src.start();const result=(await offline.startRendering()).getChannelData(0);const wav=new ArrayBuffer(44+result.length*2),v=new DataView(wav);const str=(at,text)=>{for(let i=0;i<text.length;i++)v.setUint8(at+i,text.charCodeAt(i));};str(0,'RIFF');v.setUint32(4,36+result.length*2,true);str(8,'WAVE');str(12,'fmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,16000,true);v.setUint32(28,32000,true);v.setUint16(32,2,true);v.setUint16(34,16,true);str(36,'data');v.setUint32(40,result.length*2,true);for(let i=0;i<result.length;i++)v.setInt16(44+i*2,Math.max(-1,Math.min(1,result[i]))*32767,true);$('record-status').textContent='Transcribing your PC microphone...';const data=await(await api('diagnostics/transcribe',{method:'POST',headers:{'Content-Type':'audio/wav'},body:wav})).json();$('record-status').textContent='Recognized: '+(data.text||'No reliable speech detected.');await refreshHistory();
 }catch(error){$('record-status').textContent=error.message;}finally{$('record-test').disabled=false;}
};
