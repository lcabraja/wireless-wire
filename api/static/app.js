const $ = s => document.querySelector(s);
let state, busy = false;
function message(value) { $('#message').textContent = value; }
async function request(path, data) {
  const response = await fetch('/api/v1/' + path, data === undefined ? {cache:'no-store'} : {
    method:'POST', headers:{'Content-Type':'application/json','X-Wireless-Wire-Request':'1'}, body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Request failed');
  return result;
}
function fields(target, pairs) {
  const element = $(target); element.replaceChildren();
  for (const [label, value] of pairs) {
    const dt=document.createElement('dt'),dd=document.createElement('dd');
    dt.textContent=label; dd.textContent=value || '—'; element.append(dt,dd);
  }
}
async function refresh() {
  if (busy) return;
  try {
    state=await request('status');
    $('#health').textContent=state.bridge ? 'Bridge online' : 'Bridge unavailable';
    fields('#network',[['Wi-Fi',state.wifi],['LAN',(state.lan_ips||[]).join(', ')],['Tailscale',state.tailnet_ip]]);
    fields('#usb',[['Device',state.usb.join(', ')||'Not connected'],['Connection',state.usb_details.map(d=>`${d.port} · ${d.speed}`).join(', ')]]);
    fields('#bridge',[[state.clients.length?'Connected client':'Last client',state.clients.join(', ')||state.last_client],['Client IP',state.client_ips.join(', ')||state.last_ip],['Sessions',String(state.sessions)]]);
    const installed=state.services['wireless-wire-display']==='active';
    $('#screen-state').textContent=installed?'Screen online':'Optional screen is not running';
    document.querySelectorAll('[data-angle]').forEach(b=>{b.disabled=!installed;b.setAttribute('aria-pressed',Number(b.dataset.angle)===state.rotation);});
    $('#updated').textContent='Updated '+new Date().toLocaleTimeString();
  } catch(e) { $('#health').textContent='Connection unavailable';message(e.message); }
}
async function action(path,data,success) {
  busy=true;document.querySelectorAll('button').forEach(b=>b.disabled=true);
  try { const result=await request(path,data);message(success);return result; }
  catch(e){message(e.message);throw e;}
  finally {busy=false;document.querySelectorAll('button').forEach(b=>b.disabled=false);await refresh();}
}
async function networks() {
  try {
    const result=await request('wifi');$('#networks').replaceChildren();
    for(const network of result.connections){
      const li=document.createElement('li'),name=document.createElement('span'),button=document.createElement('button');
      name.textContent=network.name;button.textContent='Connect';
      button.onclick=()=>{if(confirm(`Switch to ${network.name}? The connection to the Pi may drop temporarily.`))action('wifi/connect',{uuid:network.uuid},'Network switch scheduled. Waiting for the Pi to reconnect.').catch(()=>{});};
      li.append(name,button);$('#networks').append(li);
    }
  }catch(e){message(e.message);}
}
document.querySelectorAll('[data-angle]').forEach(b=>b.onclick=()=>action('display/rotation',{degrees:Number(b.dataset.angle)},'Screen orientation saved.').catch(()=>{}));
$('#restart').onclick=()=>{if(confirm('Restart the bridge? Active USB sessions will disconnect.'))action('service/restart',{service:'wireless-wire'},'Bridge restarted.').catch(()=>{});};
$('#wifi-form').onsubmit=async e=>{e.preventDefault();const form=e.currentTarget;try{await action('wifi',{ssid:form.ssid.value,password:form.password.value},'Wi-Fi network saved. Current connection kept.');form.password.value='';await networks();}catch{}};
$('#download').onclick=async()=>{try{const result=await action('client-config',{},'Private client configuration downloaded.');const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='wireless-wire-client.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch{}};
$('#setup').textContent=`python3 scripts/install-client.py --api-url ${location.origin}`;
refresh();networks();setInterval(refresh,5000);
