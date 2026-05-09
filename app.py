import os
import tempfile
import threading
import shutil
import re
import time
from flask import Flask, request, jsonify, send_file
import yt_dlp

app = Flask(__name__)

TEMP_BASE = os.path.join(tempfile.gettempdir(), 'youtube_dl_temp')
os.makedirs(TEMP_BASE, exist_ok=True)

COOKIE_FILE = os.path.join(os.path.dirname(__file__), 'cookies.txt')

def get_ydl_opts(extra_opts=None):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'retries': 30,
        'ignoreerrors': True,
    }
    if os.path.exists(COOKIE_FILE):
        opts['cookiefile'] = COOKIE_FILE
    if extra_opts:
        opts.update(extra_opts)
    return opts

# 軽量青色アニメーションHTML
HTML = '''
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>💙 YouTube Downloader</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body {
            background: linear-gradient(135deg, #0a0a2a, #1a1a4a);
            font-family: 'Segoe UI', system-ui;
            min-height: 100vh;
            padding: 20px;
            animation: bgPulse 3s ease infinite;
        }
        @keyframes bgPulse { 0%,100%{background:#0a0a2a} 50%{background:#1a1a4a} }
        
        .container { max-width: 1000px; margin: 0 auto; }
        
        .card {
            background: rgba(30,30,80,0.9);
            backdrop-filter: blur(10px);
            border-radius: 28px;
            padding: 30px;
            border: 1px solid #4488ff;
            animation: slideUp 0.5s ease;
        }
        @keyframes slideUp { from{opacity:0;transform:translateY(30px)} to{opacity:1;transform:translateY(0)} }
        
        h1 {
            text-align: center;
            color: #88aaff;
            font-size: 2rem;
            margin-bottom: 10px;
            animation: textGlow 2s ease infinite;
        }
        @keyframes textGlow { 0%,100%{text-shadow:0 0 5px#4488ff} 50%{text-shadow:0 0 20px#4488ff} }
        
        .sub { text-align: center; color: #aaaaff; margin-bottom: 30px; }
        
        .mode-switch {
            display: flex;
            gap: 15px;
            justify-content: center;
            margin-bottom: 25px;
        }
        .mode-btn {
            padding: 10px 25px;
            border-radius: 40px;
            border: 2px solid #4488ff;
            background: transparent;
            color: #aaaaff;
            cursor: pointer;
            transition: all 0.3s;
        }
        .mode-btn.active, .mode-btn:hover {
            background: #4488ff;
            color: white;
            transform: scale(1.05);
        }
        
        .row { display: flex; gap: 25px; flex-wrap: wrap; }
        .left { flex: 1.5; min-width: 280px; }
        .right { flex: 1; min-width: 240px; }
        
        input, select, button {
            width: 100%;
            padding: 12px 16px;
            margin: 8px 0;
            border-radius: 40px;
            border: 2px solid #4488ff;
            background: rgba(20,20,60,0.8);
            color: white;
            font-size: 14px;
        }
        input:focus { outline: none; border-color: #88aaff; box-shadow: 0 0 10px #4488ff; }
        
        button {
            background: linear-gradient(135deg, #4488ff, #2244aa);
            cursor: pointer;
            border: none;
            transition: all 0.3s;
        }
        button:hover { transform: translateY(-2px); box-shadow: 0 5px 15px #4488ff; }
        
        .info-panel {
            background: rgba(40,40,100,0.5);
            border-radius: 16px;
            padding: 15px;
            margin-top: 15px;
            border: 1px solid #4488ff;
            animation: fadeIn 0.5s;
        }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        
        .info-item {
            display: flex;
            align-items: center;
            gap: 10px;
            margin: 8px 0;
            padding: 5px;
        }
        
        .progress-area {
            margin-top: 15px;
            display: none;
        }
        .progress-bar {
            height: 20px;
            background: rgba(40,40,100,0.5);
            border-radius: 10px;
            overflow: hidden;
        }
        .progress-fill {
            width: 0%;
            height: 100%;
            background: linear-gradient(90deg, #4488ff, #88aaff);
            transition: width 0.3s;
            animation: progressShine 1.5s infinite;
        }
        @keyframes progressShine { 0%{opacity:0.7} 50%{opacity:1} 100%{opacity:0.7} }
        
        .loading {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid #4488ff;
            border-top-color: white;
            border-radius: 50%;
            animation: spin 0.6s linear infinite;
            margin-right: 8px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        
        @media (max-width: 700px) { .row { flex-direction: column; } .card { padding: 20px; } h1 { font-size: 1.5rem; } }
    </style>
</head>
<body>
<div class="container">
    <div class="card">
        <h1>💙 YouTube Downloader</h1>
        <div class="sub">動画 | 音声 | サムネイル</div>
        
        <div class="mode-switch">
            <button class="mode-btn active" id="videoMode">🎬 動画</button>
            <button class="mode-btn" id="audioMode">🎵 音声</button>
            <button class="mode-btn" id="thumbMode">🖼️ サムネイル</button>
        </div>
        
        <div class="row">
            <div class="left">
                <input type="text" id="url" placeholder="YouTube URL">
                <button id="infoBtn">🔍 情報取得</button>
                <div id="infoPanel" class="info-panel" style="display:none"></div>
            </div>
            <div class="right">
                <div id="videoSetting"><select id="quality"><option>画質を選択</option></select></div>
                <div id="audioSetting" style="display:none"><select id="audioFormat"><option value="mp3">MP3</option><option value="m4a">M4A</option><option value="opus">OPUS</option></select></div>
                <div id="thumbSetting" style="display:none">
                    <select id="thumbSize">
                        <option value="default">標準</option>
                        <option value="mqdefault">中</option>
                        <option value="hqdefault">高</option>
                        <option value="maxresdefault">最大</option>
                    </select>
                </div>
                <div id="progressArea" class="progress-area"><div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div><div id="progressMsg" style="text-align:center;margin-top:8px;color:#aaaaff"></div></div>
                <div id="saveContainer" style="display:none"><button id="saveBtn">💾 ダウンロード</button></div>
            </div>
        </div>
    </div>
</div>

<script>
    let formats=[], selectedItag=null, currentUrl='', videoTitle='', currentMode='video';
    let thumbnails=[], videoId='';
    
    function setMode(mode) {
        currentMode = mode;
        document.querySelectorAll('.mode-btn').forEach(b=>b.classList.remove('active'));
        document.getElementById(mode+'Mode').classList.add('active');
        document.getElementById('videoSetting').style.display = mode==='video'?'block':'none';
        document.getElementById('audioSetting').style.display = mode==='audio'?'block':'none';
        document.getElementById('thumbSetting').style.display = mode==='thumb'?'block':'none';
        document.getElementById('saveContainer').style.display = 'none';
        document.getElementById('infoPanel').style.display = 'none';
    }
    document.getElementById('videoMode').onclick=()=>setMode('video');
    document.getElementById('audioMode').onclick=()=>setMode('audio');
    document.getElementById('thumbMode').onclick=()=>setMode('thumb');
    
    document.getElementById('infoBtn').onclick=async function(){
        let url=document.getElementById('url').value.trim();
        if(!url){alert('URLを入力');return;}
        currentUrl=url;
        this.disabled=true;
        this.innerHTML='<span class="loading"></span> 取得中...';
        try{
            let res=await fetch('/video_info',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})});
            let data=await res.json();
            if(data.success){
                videoTitle=data.title;
                formats=data.formats||[];
                thumbnails=data.thumbnails||[];
                videoId=data.video_id||'';
                let qs=document.getElementById('quality');
                qs.innerHTML='<option>画質を選択</option>';
                for(let f of formats){
                    let opt=document.createElement('option');
                    opt.value=f.itag;
                    opt.textContent=f.height+'p'+(f.has_audio?' 🔊':'');
                    qs.appendChild(opt);
                }
                let def=formats.find(f=>f.height===720)||formats[0];
                if(def){selectedItag=def.itag;qs.value=selectedItag;}
                
                let thumbHtml='<div class="info-item">📹 '+escapeHtml(data.title)+'</div><div class="info-item">👁️ '+formatNumber(data.view_count)+'</div>';
                if(thumbnails.length) thumbHtml+='<div class="info-item">🖼️ <img src="'+thumbnails[0].url+'" style="height:60px;border-radius:8px"></div>';
                document.getElementById('infoPanel').innerHTML=thumbHtml;
                document.getElementById('infoPanel').style.display='block';
                document.getElementById('saveContainer').style.display='block';
            }else alert('失敗:'+data.error);
        }catch(e){alert('エラー');}
        finally{this.disabled=false;this.innerHTML='🔍 情報取得';}
    };
    
    document.getElementById('quality').onchange=function(){selectedItag=parseInt(this.value);};
    
    document.getElementById('saveBtn').onclick=async function(){
        this.disabled=true;
        let pa=document.getElementById('progressArea'),pf=document.getElementById('progressFill'),pm=document.getElementById('progressMsg');
        pa.style.display='block';
        pf.style.width='0%';
        pm.innerHTML='準備中...';
        let p=0,iv=setInterval(()=>{if(p<90){p+=10;pf.style.width=p+'%';}},500);
        try{
            let body={url:currentUrl,title:videoTitle,type:currentMode};
            if(currentMode==='video'){if(!selectedItag)throw new Error('画質選択');body.itag=selectedItag;}
            if(currentMode==='audio')body.audio_format=document.getElementById('audioFormat').value;
            if(currentMode==='thumb'){body.size=document.getElementById('thumbSize').value;body.video_id=videoId;}
            let res=await fetch('/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
            clearInterval(iv);
            if(!res.ok){let err=await res.json();throw new Error(err.error);}
            let blob=await res.blob();
            let a=document.createElement('a'),url=URL.createObjectURL(blob);
            a.href=url;
            a.download={video:'video.mp4',audio:'audio.mp3',thumb:'thumbnail.jpg'}[currentMode];
            a.click();
            URL.revokeObjectURL(url);
            pf.style.width='100%';pm.innerHTML='✅完了！';
            setTimeout(()=>{pa.style.display='none';this.disabled=false;},2000);
        }catch(e){clearInterval(iv);alert('失敗:'+e.message);pa.style.display='none';this.disabled=false;}
    };
    
    function escapeHtml(s){if(!s)return '';return s.replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m]));}
    function formatNumber(n){if(n>=100000000)return (n/100000000).toFixed(1)+'億';if(n>=10000)return (n/10000).toFixed(1)+'万';return n.toString();}
    document.getElementById('url').onkeypress=e=>{if(e.key==='Enter')document.getElementById('infoBtn').click();};
</script>
</body>
</html>
'''

def sanitize_filename(title):
    if not title:
        return 'video'
    name = re.sub(r'[\\/*?:"<>|]', '', title)
    name = re.sub(r'[#%&{}\\[\]~!$^@+/=,]', '_', name)
    return name[:100] if name else 'video'

@app.route('/')
def index():
    return HTML

@app.route('/video_info', methods=['POST'])
def video_info():
    data = request.get_json()
    url = data['url']
    if 'youtu.be' in url:
        url = f'https://www.youtube.com/watch?v={url.split("/")[-1].split("?")[0]}'
    try:
        with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = []
            for f in info.get('formats', []):
                if '-drc' not in str(f['format_id']) and f.get('vcodec') != 'none' and f.get('height'):
                    formats.append({
                        'itag': str(f['format_id']),
                        'height': f['height'],
                        'has_audio': f.get('acodec') != 'none',
                        'preview_url': f.get('url', '')
                    })
            formats.sort(key=lambda x: -x['height'])
            thumbnails = [{'size': s, 'url': f'https://img.youtube.com/vi/{info.get("id", "")}/{s}.jpg'} for s in ['default','mqdefault','hqdefault','maxresdefault']]
            return jsonify({'success': True, 'title': info.get('title'), 'view_count': info.get('view_count', 0), 'duration': info.get('duration_string'), 'formats': formats, 'thumbnails': thumbnails, 'video_id': info.get('id')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/download', methods=['POST'])
def download():
    data = request.get_json()
    url = data['url']
    download_type = data.get('type', 'video')
    safe_title = sanitize_filename(data.get('title', 'video'))
    temp_dir = tempfile.mkdtemp(dir=TEMP_BASE)
    
    try:
        if download_type == 'video':
            itag = data.get('itag')
            output_template = os.path.join(temp_dir, 'video.%(ext)s')
            ydl_opts = get_ydl_opts({'format': f'{itag}+bestaudio/best', 'outtmpl': output_template, 'merge_output_format': 'mp4'})
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
            for f in os.listdir(temp_dir):
                if f.endswith(('.mp4', '.webm', '.mkv')):
                    actual = os.path.join(temp_dir, f); break
            new_path = os.path.join(temp_dir, f'{safe_title}.mp4')
            os.rename(actual, new_path)
            return send_file(new_path, mimetype='video/mp4', as_attachment=True, download_name=f'{safe_title}.mp4')
            
        elif download_type == 'audio':
            audio_format = data.get('audio_format', 'mp3')
            output_template = os.path.join(temp_dir, f'{safe_title}.%(ext)s')
            ydl_opts = get_ydl_opts({'format': 'bestaudio/best', 'outtmpl': output_template, 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': audio_format, 'preferredquality': '192'}]})
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
            for f in os.listdir(temp_dir):
                if f.endswith(f'.{audio_format}'):
                    actual = os.path.join(temp_dir, f); break
            mime = {'mp3': 'audio/mpeg', 'm4a': 'audio/mp4', 'opus': 'audio/opus'}.get(audio_format, 'audio/mpeg')
            return send_file(actual, mimetype=mime, as_attachment=True, download_name=os.path.basename(actual))
            
        else:  # thumbnail
            video_id = data.get('video_id', '')
            if not video_id:
                with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
                    info = ydl.extract_info(url, download=False)
                    video_id = info.get('id', '')
            size = data.get('size', 'maxresdefault')
            thumb_url = f'https://img.youtube.com/vi/{video_id}/{size}.jpg'
            actual = os.path.join(temp_dir, f'{safe_title}.jpg')
            import urllib.request
            urllib.request.urlretrieve(thumb_url, actual)
            return send_file(actual, mimetype='image/jpeg', as_attachment=True, download_name=f'{safe_title}.jpg')
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        threading.Thread(target=lambda: (time.sleep(5), shutil.rmtree(temp_dir, ignore_errors=True))).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)