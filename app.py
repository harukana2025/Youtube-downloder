import os
import tempfile
import threading
import shutil
import re
import time
import glob
import urllib.request
from flask import Flask, request, jsonify, render_template_string, Response
import yt_dlp

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024

TEMP_BASE = os.path.join(tempfile.gettempdir(), 'youtube_dl_temp')
os.makedirs(TEMP_BASE, exist_ok=True)

# 環境変数からクッキーを読み込み
COOKIE_CONTENT = os.environ.get('YOUTUBE_COOKIES', '')
COOKIE_FILE = None

if COOKIE_CONTENT:
    temp_cookie = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt')
    temp_cookie.write(COOKIE_CONTENT)
    temp_cookie.close()
    COOKIE_FILE = temp_cookie.name
    print("🍪 環境変数からクッキーを読み込みました")

def get_ffmpeg_path():
    try:
        import subprocess
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True)
        if result.returncode == 0:
            return 'ffmpeg'
    except:
        pass
    return None

FFMPEG_PATH = get_ffmpeg_path()

def get_ydl_opts(extra_opts=None):
    opts = {
        'quiet': True,
        'no_warnings': False,
        'retries': 30,
    }
    if FFMPEG_PATH:
        opts['ffmpeg_location'] = FFMPEG_PATH
    if COOKIE_FILE and os.path.exists(COOKIE_FILE):
        opts['cookiefile'] = COOKIE_FILE
    if extra_opts:
        opts.update(extra_opts)
    return opts

def download_thumbnail(url, save_path):
    try:
        urllib.request.urlretrieve(url, save_path)
        return True
    except Exception as e:
        print(f"サムネイルDLエラー: {e}")
        return False

# ライブ視聴用HTML
LIVE_HTML = '''
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🔴 YouTube Live - リアルタイム視聴</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
            min-height: 100vh;
            padding: 20px;
        }
        .live-container { max-width: 1600px; margin: 0 auto; }
        .live-badge {
            display: inline-block;
            background: #ff4757;
            color: white;
            padding: 5px 15px;
            border-radius: 30px;
            font-size: 14px;
            font-weight: bold;
            animation: pulse 1.5s infinite;
            margin-right: 10px;
        }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }
        .live-header {
            background: rgba(0,0,0,0.5);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .live-title { color: white; font-size: 1.5rem; margin-top: 10px; }
        .split-layout { display: flex; gap: 20px; flex-wrap: wrap; }
        .video-section { flex: 2.5; min-width: 500px; }
        .chat-section {
            flex: 1;
            min-width: 350px;
            background: rgba(0,0,0,0.6);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            display: flex;
            flex-direction: column;
            height: 80vh;
            position: sticky;
            top: 20px;
        }
        .chat-header { padding: 15px; border-bottom: 1px solid rgba(255,255,255,0.2); color: white; font-weight: bold; }
        .chat-messages { flex: 1; overflow-y: auto; padding: 15px; }
        .chat-message { margin-bottom: 12px; padding: 8px 12px; background: rgba(255,255,255,0.08); border-radius: 12px; word-break: break-word; animation: fadeIn 0.3s ease; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        .chat-author { font-weight: bold; color: #ffd700; margin-right: 10px; }
        .chat-text { color: rgba(255,255,255,0.9); }
        .video-container { background: #000; border-radius: 20px; overflow: hidden; margin-bottom: 20px; }
        video { width: 100%; max-height: 60vh; background: #000; }
        .quality-selector { display: flex; gap: 10px; flex-wrap: wrap; margin: 15px 0; }
        .quality-btn { background: rgba(255,255,255,0.2); border: none; padding: 8px 16px; border-radius: 30px; color: white; cursor: pointer; transition: all 0.3s; }
        .quality-btn:hover, .quality-btn.active { background: linear-gradient(135deg, #667eea, #764ba2); }
        .download-live-btn { background: linear-gradient(135deg, #28a745, #20c997); border: none; padding: 12px 24px; border-radius: 40px; color: white; font-weight: bold; cursor: pointer; margin-top: 15px; width: 100%; }
        .back-link { display: inline-block; margin-top: 20px; color: rgba(255,255,255,0.7); text-decoration: none; }
        .back-link:hover { color: white; }
        .view-count { font-size: 14px; color: #aaa; }
        .progress-area { margin-top: 15px; display: none; }
        .progress-bar { width: 100%; height: 6px; background: rgba(255,255,255,0.2); border-radius: 3px; overflow: hidden; }
        .progress-fill { width: 0%; height: 100%; background: #28a745; transition: width 0.3s; }
        .chat-status { font-size: 12px; color: rgba(255,255,255,0.5); padding: 10px 15px; border-top: 1px solid rgba(255,255,255,0.1); }
        @media (max-width: 900px) {
            .split-layout { flex-direction: column; }
            .chat-section { height: 500px; position: relative; }
            .video-section { min-width: auto; }
        }
    </style>
</head>
<body>
<div class="live-container">
    <div class="live-header">
        <div><span class="live-badge">🔴 LIVE</span><span class="view-count" id="viewCount">👁️ 視聴中...</span></div>
        <div class="live-title">{{ title }}</div>
    </div>
    <div class="split-layout">
        <div class="video-section">
            <div class="video-container"><video id="videoPlayer" controls autoplay playsinline><source id="videoSource" src=""></video></div>
            <div class="quality-selector" id="qualitySelector"></div>
            <button id="downloadLiveBtn" class="download-live-btn">📥 ライブ録画ダウンロード</button>
            <div id="progressArea" class="progress-area"><div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div><div id="progressMsg" class="live-info" style="text-align:center"></div></div>
            <a href="/" class="back-link">← トップに戻る</a>
        </div>
        <div class="chat-section">
            <div class="chat-header">💬 ライブチャット</div>
            <div id="chatMessages" class="chat-messages"></div>
            <div class="chat-status"><span id="chatStatus">コメントを読み込み中...</span><span id="chatCount" style="float: right;">0件</span></div>
        </div>
    </div>
</div>
<script>
    let formats = [], currentStreamUrl = null, videoUrl = '{{ video_url }}', videoId = '{{ video_id }}', chatInterval = null, lastCommentId = null;
    const videoPlayer = document.getElementById('videoPlayer'), videoSource = document.getElementById('videoSource'), qualitySelector = document.getElementById('qualitySelector'), chatMessages = document.getElementById('chatMessages');
    async function loadStreams() {
        try {
            const res = await fetch('/live_streams', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: videoUrl }) });
            const data = await res.json();
            if (data.success && data.formats) {
                formats = data.formats;
                qualitySelector.innerHTML = '';
                for (let f of formats) {
                    const btn = document.createElement('button');
                    btn.className = 'quality-btn';
                    let label = f.height >= 1080 ? '🎬 ' + f.height + 'p' : '📺 ' + f.height + 'p';
                    if (f.fps && f.fps > 30) label += ' 🎯' + f.fps + 'fps';
                    btn.textContent = label;
                    if (f.height === 720) btn.classList.add('active');
                    btn.onclick = (function(fmt) { return function() { changeQuality(fmt); }; })(f);
                    qualitySelector.appendChild(btn);
                }
                let def = formats.find(f => f.height === 720) || formats[0];
                if (def) changeQuality(def);
            }
        } catch(e) { console.error(e); }
    }
    function changeQuality(fmt) {
        document.querySelectorAll('.quality-btn').forEach(btn => btn.classList.remove('active'));
        if (event && event.target) event.target.classList.add('active');
        currentStreamUrl = fmt.stream_url;
        videoSource.src = currentStreamUrl;
        videoPlayer.load();
        videoPlayer.play().catch(e => console.log('自動再生失敗:', e));
    }
    async function loadChat() {
        try {
            const res = await fetch('/live_chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ video_id: videoId, last_id: lastCommentId || '' }) });
            const data = await res.json();
            if (data.success && data.messages) {
                for (let m of data.messages) {
                    if (document.querySelector(`.chat-message[data-id="${m.id}"]`)) continue;
                    const div = document.createElement('div');
                    div.className = 'chat-message';
                    div.setAttribute('data-id', m.id);
                    div.innerHTML = `<span class="chat-author">${escapeHtml(m.author)}</span><span class="chat-text">${escapeHtml(m.message)}</span>`;
                    chatMessages.appendChild(div);
                    lastCommentId = m.id;
                }
                chatMessages.scrollTop = chatMessages.scrollHeight;
                document.getElementById('chatCount').innerText = chatMessages.children.length + '件';
            }
        } catch(e) { console.error(e); }
    }
    async function updateViewCount() {
        try {
            const res = await fetch('/live_info', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ video_id: videoId }) });
            const data = await res.json();
            if (data.success) document.getElementById('viewCount').innerHTML = `👁️ ${data.view_count} 視聴中`;
        } catch(e) {}
    }
    function escapeHtml(s) { if (!s) return ''; return s.replace(/[&<>]/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[m])); }
    document.getElementById('downloadLiveBtn').onclick = async function() {
        const active = document.querySelector('.quality-btn.active');
        const height = active ? parseInt(active.textContent.match(/\d+p/)?.[0] || '720') : 720;
        const fmt = formats.find(f => f.height === height);
        if (!fmt) return alert('画質が見つかりません');
        this.disabled = true;
        const pa = document.getElementById('progressArea'), pf = document.getElementById('progressFill'), pm = document.getElementById('progressMsg');
        pa.style.display = 'block'; pf.style.width = '0%'; pm.innerHTML = '📡 ライブ録画準備中...';
        let progress = 0, interval = setInterval(() => { if (progress < 90) { progress += 10; pf.style.width = progress + '%'; } }, 500);
        try {
            const res = await fetch('/download_live', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: videoUrl, itag: fmt.itag, title: '{{ title }}' }) });
            clearInterval(interval);
            if (!res.ok) { const err = await res.json(); throw new Error(err.error); }
            const blob = await res.blob();
            const cd = res.headers.get('Content-Disposition');
            let filename = 'live_video.mp4';
            if (cd) { const m = cd.match(/filename[*]=?.*?''([^"]+)/); if (m && m[1]) filename = decodeURIComponent(m[1]); }
            const a = document.createElement('a'), url = URL.createObjectURL(blob);
            a.href = url; a.download = filename; document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
            pf.style.width = '100%'; pm.innerHTML = '✅ 録画完了！';
            setTimeout(() => { pa.style.display = 'none'; this.disabled = false; }, 3000);
        } catch(e) { clearInterval(interval); alert('失敗: ' + e.message); pa.style.display = 'none'; this.disabled = false; }
    };
    loadStreams(); loadChat(); chatInterval = setInterval(loadChat, 8000); setInterval(updateViewCount, 10000);
    window.addEventListener('beforeunload', () => { if (chatInterval) clearInterval(chatInterval); });
</script>
</body>
</html>
'''

# メインHTML（アニメーション付き4機能版）
MAIN_HTML = '''
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>✨ YouTube ダウンローダー ✨</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            position: relative;
            overflow-x: hidden;
        }
        .bg-animation {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: 0;
            overflow: hidden;
        }
        .bg-animation div {
            position: absolute;
            display: block;
            width: 20px;
            height: 20px;
            background: rgba(255, 255, 255, 0.1);
            bottom: -150px;
            animation: floatUp 15s infinite;
            border-radius: 50%;
        }
        @keyframes floatUp {
            0% { transform: translateY(0) rotate(0deg); opacity: 1; }
            100% { transform: translateY(-1000px) rotate(720deg); opacity: 0; }
        }
        .container { max-width: 1300px; margin: 0 auto; position: relative; z-index: 1; animation: fadeInUp 0.8s ease-out; }
        @keyframes fadeInUp { from { opacity: 0; transform: translateY(30px); } to { opacity: 1; transform: translateY(0); } }
        .card {
            background: rgba(255, 255, 255, 0.98);
            backdrop-filter: blur(10px);
            border-radius: 32px;
            padding: 40px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            transition: transform 0.3s ease;
        }
        .card:hover { transform: translateY(-5px); }
        .header { text-align: center; margin-bottom: 30px; }
        .header h1 {
            background: linear-gradient(135deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            font-size: 2.5rem;
        }
        .mode-switch {
            display: flex;
            gap: 15px;
            justify-content: center;
            margin-bottom: 30px;
            flex-wrap: wrap;
        }
        .mode-btn {
            padding: 12px 30px;
            border-radius: 50px;
            border: 2px solid #667eea;
            background: white;
            color: #667eea;
            cursor: pointer;
            font-weight: bold;
            transition: all 0.3s;
        }
        .mode-btn.active, .mode-btn:hover {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            border-color: transparent;
            transform: scale(1.05);
        }
        .row { display: flex; gap: 30px; flex-wrap: wrap; }
        .left { flex: 1.5; min-width: 300px; }
        .right { flex: 1; min-width: 280px; }
        input, select, button {
            width: 100%;
            padding: 14px 20px;
            margin: 10px 0;
            border-radius: 50px;
            border: 2px solid #e0e0e0;
            font-size: 16px;
            transition: all 0.3s;
        }
        input:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102,126,234,0.1);
        }
        button {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            font-weight: bold;
            cursor: pointer;
            border: none;
            position: relative;
            overflow: hidden;
        }
        button::before {
            content: '';
            position: absolute;
            top: 50%;
            left: 50%;
            width: 0;
            height: 0;
            border-radius: 50%;
            background: rgba(255,255,255,0.5);
            transform: translate(-50%, -50%);
            transition: width 0.6s, height 0.6s;
        }
        button:hover::before { width: 300px; height: 300px; }
        button:hover { transform: translateY(-2px); }
        .video-wrapper { background: #000; border-radius: 20px; overflow: hidden; margin: 20px 0; }
        video { width: 100%; display: block; }
        .info-panel {
            background: linear-gradient(135deg, #f5f7fa, #c3cfe2);
            border-radius: 20px;
            padding: 20px;
            margin-top: 20px;
            animation: slideInLeft 0.5s ease;
        }
        @keyframes slideInLeft { from { opacity: 0; transform: translateX(-30px); } to { opacity: 1; transform: translateX(0); } }
        .info-item { display: flex; align-items: center; gap: 10px; margin: 10px 0; padding: 8px; border-radius: 12px; transition: background 0.3s; }
        .info-item:hover { background: rgba(255,255,255,0.5); transform: translateX(5px); }
        .thumbnail-preview { margin-top: 15px; text-align: center; }
        .thumbnail-preview img { max-width: 100%; border-radius: 15px; box-shadow: 0 5px 15px rgba(0,0,0,0.2); }
        .progress-area { margin-top: 20px; display: none; animation: fadeIn 0.5s ease; }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        .progress-bar {
            width: 100%;
            height: 30px;
            background: #e0e0e0;
            border-radius: 15px;
            overflow: hidden;
        }
        .progress-fill {
            width: 0%;
            height: 100%;
            background: linear-gradient(90deg, #28a745, #20c997);
            border-radius: 15px;
            transition: width 0.3s;
            position: relative;
            overflow: hidden;
        }
        .progress-fill::after {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            bottom: 0;
            right: 0;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
            animation: shimmer 1.5s infinite;
        }
        @keyframes shimmer { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }
        .progress-text { text-align: center; margin-top: 10px; color: #666; font-weight: bold; }
        .loading-spinner {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid rgba(255,255,255,0.3);
            border-radius: 50%;
            border-top-color: white;
            animation: spin 0.8s linear infinite;
            margin-right: 10px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .quality-badge {
            display: inline-block;
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
            margin: 0 5px;
        }
        .thumbnail-options {
            background: #f8f9fa;
            border-radius: 15px;
            padding: 15px;
            margin-top: 15px;
        }
        .size-btns { display: flex; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
        .size-btn {
            flex: 1;
            padding: 8px;
            margin: 0;
            background: #e0e0e0;
            color: #333;
            font-size: 14px;
            border-radius: 30px;
        }
        .size-btn.active { background: linear-gradient(135deg, #667eea, #764ba2); color: white; }
        .live-notice {
            background: linear-gradient(135deg, #ff4757, #ff6b81);
            color: white;
            padding: 10px;
            border-radius: 10px;
            text-align: center;
            margin-top: 10px;
            animation: pulseNotice 1.5s infinite;
        }
        @keyframes pulseNotice { 0%,100% { opacity: 1; } 50% { opacity: 0.7; } }
        @media (max-width: 768px) { .card { padding: 20px; } .header h1 { font-size: 1.8rem; } }
    </style>
</head>
<body>
    <div class="bg-animation" id="bgAnimation"></div>
    <div class="container">
        <div class="card">
            <div class="header">
                <h1>✨ YouTube ダウンローダー ✨</h1>
                <p>動画 | 音声 | サムネイル | ライブ視聴</p>
                <div><span class="quality-badge">🎬 動画</span><span class="quality-badge">🎵 音声</span><span class="quality-badge">🖼️ サムネイル</span><span class="quality-badge">🔴 ライブ</span></div>
            </div>
            <div class="mode-switch">
                <button class="mode-btn active" id="videoModeBtn">🎬 動画</button>
                <button class="mode-btn" id="audioModeBtn">🎵 音声</button>
                <button class="mode-btn" id="thumbnailModeBtn">🖼️ サムネイル</button>
            </div>
            <div class="row">
                <div class="left">
                    <input type="text" id="urlInput" placeholder="YouTube URL を入力">
                    <button id="infoBtn">🔍 情報取得</button>
                    <div id="videoContainer" style="display:none"><div class="video-wrapper"><video id="videoPreview" controls><source id="videoSource" src=""></video></div></div>
                    <div id="thumbnailPreview" class="thumbnail-preview" style="display:none"><img id="thumbnailImg" alt="サムネイル"></div>
                    <div id="infoText" class="info-panel" style="display:none"></div>
                    <div id="liveNotice" class="live-notice" style="display:none">🔴 ライブ配信です！<br><a href="#" id="liveLink" style="color:white; font-weight:bold;">こちらから視聴</a></div>
                </div>
                <div class="right">
                    <h3 id="downloadLabel">⚙️ ダウンロード設定</h3>
                    <div id="videoSettings"><select id="qualitySelect"><option>画質を選択</option></select></div>
                    <div id="audioSettings" style="display:none"><div class="thumbnail-options"><label>🎵 音声フォーマット</label><select id="audioFormatSelect"><option value="mp3">MP3</option><option value="m4a">M4A</option><option value="opus">OPUS</option><option value="wav">WAV</option></select></div></div>
                    <div id="thumbnailSettings" style="display:none"><div class="thumbnail-options"><label>🖼️ サムネイルサイズ</label><div class="size-btns"><button class="size-btn" data-size="default">標準</button><button class="size-btn" data-size="mqdefault">中</button><button class="size-btn" data-size="hqdefault">高</button><button class="size-btn" data-size="sddefault">HD</button><button class="size-btn active" data-size="maxresdefault">最大</button></div></div></div>
                    <div id="progressArea" class="progress-area"><div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div><div class="progress-text" id="progressMsg">準備完了</div></div>
                    <div id="saveContainer" style="display:none"><button id="saveBtn">💾 ダウンロード</button></div>
                </div>
            </div>
        </div>
    </div>
    <script>
        function createBackgroundBubbles() {
            const bg = document.getElementById('bgAnimation');
            for (let i = 0; i < 50; i++) {
                const bubble = document.createElement('div');
                const size = Math.random() * 60 + 10;
                bubble.style.width = size + 'px';
                bubble.style.height = size + 'px';
                bubble.style.left = Math.random() * 100 + '%';
                bubble.style.animationDelay = Math.random() * 15 + 's';
                bubble.style.animationDuration = (Math.random() * 10 + 10) + 's';
                bg.appendChild(bubble);
            }
        }
        createBackgroundBubbles();

        let formats = [], selectedItag = null, currentUrl = '', videoTitle = '', currentMode = 'video';
        let thumbnails = [], selectedThumbSize = 'maxresdefault', isLive = false, videoId = '';

        document.getElementById('videoModeBtn').onclick = () => {
            currentMode = 'video';
            document.getElementById('videoModeBtn').classList.add('active');
            document.getElementById('audioModeBtn').classList.remove('active');
            document.getElementById('thumbnailModeBtn').classList.remove('active');
            document.getElementById('videoSettings').style.display = 'block';
            document.getElementById('audioSettings').style.display = 'none';
            document.getElementById('thumbnailSettings').style.display = 'none';
            document.getElementById('saveContainer').style.display = 'none';
            document.getElementById('infoText').style.display = 'none';
            document.getElementById('videoContainer').style.display = 'none';
            document.getElementById('thumbnailPreview').style.display = 'none';
            document.getElementById('liveNotice').style.display = 'none';
            document.getElementById('downloadLabel').innerHTML = '⚙️ 動画ダウンロード設定';
        };
        document.getElementById('audioModeBtn').onclick = () => {
            currentMode = 'audio';
            document.getElementById('audioModeBtn').classList.add('active');
            document.getElementById('videoModeBtn').classList.remove('active');
            document.getElementById('thumbnailModeBtn').classList.remove('active');
            document.getElementById('videoSettings').style.display = 'none';
            document.getElementById('audioSettings').style.display = 'block';
            document.getElementById('thumbnailSettings').style.display = 'none';
            document.getElementById('saveContainer').style.display = 'none';
            document.getElementById('infoText').style.display = 'none';
            document.getElementById('videoContainer').style.display = 'none';
            document.getElementById('thumbnailPreview').style.display = 'none';
            document.getElementById('liveNotice').style.display = 'none';
            document.getElementById('downloadLabel').innerHTML = '🎵 音声ダウンロード設定';
        };
        document.getElementById('thumbnailModeBtn').onclick = () => {
            currentMode = 'thumbnail';
            document.getElementById('thumbnailModeBtn').classList.add('active');
            document.getElementById('videoModeBtn').classList.remove('active');
            document.getElementById('audioModeBtn').classList.remove('active');
            document.getElementById('videoSettings').style.display = 'none';
            document.getElementById('audioSettings').style.display = 'none';
            document.getElementById('thumbnailSettings').style.display = 'block';
            document.getElementById('saveContainer').style.display = 'none';
            document.getElementById('infoText').style.display = 'none';
            document.getElementById('videoContainer').style.display = 'none';
            document.getElementById('thumbnailPreview').style.display = 'none';
            document.getElementById('liveNotice').style.display = 'none';
            document.getElementById('downloadLabel').innerHTML = '🖼️ サムネイル設定';
        };

        document.querySelectorAll('.size-btn').forEach(btn => {
            btn.onclick = () => {
                document.querySelectorAll('.size-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                selectedThumbSize = btn.dataset.size;
                if (thumbnails.length) updateThumbPreview();
            };
        });

        function updateThumbPreview() {
            let thumb = thumbnails.find(t => t.size === selectedThumbSize) || thumbnails[0];
            if (thumb && thumb.url) {
                document.getElementById('thumbnailImg').src = thumb.url;
                document.getElementById('thumbnailPreview').style.display = 'block';
            }
        }

        document.getElementById('infoBtn').onclick = async function() {
            const url = document.getElementById('urlInput').value.trim();
            if (!url) { alert('URLを入力してください'); return; }
            currentUrl = url;
            this.disabled = true;
            this.innerHTML = '<span class="loading-spinner"></span> 取得中...';
            try {
                const res = await fetch('/video_info', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }) });
                const data = await res.json();
                if (data.success) {
                    videoTitle = data.title;
                    formats = data.formats || [];
                    thumbnails = data.thumbnails || [];
                    isLive = data.is_live || false;
                    videoId = data.video_id || '';

                    if (isLive) {
                        document.getElementById('liveNotice').style.display = 'block';
                        document.getElementById('liveLink').href = '/live/' + encodeURIComponent(currentUrl);
                    }

                    const qs = document.getElementById('qualitySelect');
                    qs.innerHTML = '<option>画質を選択</option>';
                    for (let f of formats) {
                        const opt = document.createElement('option');
                        opt.value = f.itag;
                        opt.textContent = f.height + 'p' + (f.fps && f.fps > 30 ? ' ' + f.fps + 'fps' : '');
                        qs.appendChild(opt);
                    }
                    let def = formats.find(f => f.height === 720) || formats[0];
                    if (def) {
                        selectedItag = def.itag;
                        qs.value = selectedItag;
                        if (def.preview_url) {
                            document.getElementById('videoSource').src = def.preview_url;
                            document.getElementById('videoPreview').load();
                            document.getElementById('videoContainer').style.display = 'block';
                        }
                    }
                    if (thumbnails.length) updateThumbPreview();
                    document.getElementById('infoText').innerHTML = `<div class="info-item">📹 <strong>${escapeHtml(data.title)}</strong></div><div class="info-item">👁️ ${formatNumber(data.view_count)} 回</div><div class="info-item">⏱️ ${data.duration || '不明'}</div><div class="info-item">🖼️ サムネイル:${thumbnails.length}種</div>${isLive ? '<div class="info-item">🔴 ライブ配信</div>' : ''}`;
                    document.getElementById('infoText').style.display = 'block';
                    document.getElementById('saveContainer').style.display = 'block';
                } else { alert('失敗: ' + data.error); }
            } catch(e) { alert('通信エラー'); }
            finally { this.disabled = false; this.innerHTML = '🔍 情報取得'; }
        };

        document.getElementById('qualitySelect').onchange = function() {
            const itag = parseInt(this.value);
            const fmt = formats.find(f => f.itag === itag);
            if (fmt && fmt.preview_url) {
                selectedItag = itag;
                document.getElementById('videoSource').src = fmt.preview_url;
                document.getElementById('videoPreview').load();
            }
        };

        document.getElementById('saveBtn').onclick = async function() {
            this.disabled = true;
            const pa = document.getElementById('progressArea'), pf = document.getElementById('progressFill'), pm = document.getElementById('progressMsg');
            pa.style.display = 'block';
            pf.style.width = '0%';
            const msgs = { video: '動画準備中...', audio: '音声抽出中...', thumbnail: 'サムネイル保存中...' };
            pm.innerHTML = msgs[currentMode];
            let progress = 0, interval = setInterval(() => { if (progress < 90) { progress += 10; pf.style.width = progress + '%'; } }, 500);
            try {
                const body = { url: currentUrl, title: videoTitle, type: currentMode };
                if (currentMode === 'video') { if (!selectedItag) throw new Error('画質を選択'); body.itag = selectedItag; }
                if (currentMode === 'audio') body.audio_format = document.getElementById('audioFormatSelect').value;
                if (currentMode === 'thumbnail') body.size = selectedThumbSize;
                const res = await fetch('/download', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
                clearInterval(interval);
                if (!res.ok) { const err = await res.json(); throw new Error(err.error); }
                const blob = await res.blob();
                const cd = res.headers.get('Content-Disposition');
                let filename = { video: 'video.mp4', audio: 'audio.mp3', thumbnail: 'thumbnail.jpg' }[currentMode];
                if (cd) { const m = cd.match(/filename[*]=?.*?''([^"]+)/); if (m && m[1]) filename = decodeURIComponent(m[1]); }
                const a = document.createElement('a'), url = URL.createObjectURL(blob);
                a.href = url; a.download = filename; document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
                pf.style.width = '100%'; pm.innerHTML = '✅ 完了！';
                setTimeout(() => { pa.style.display = 'none'; this.disabled = false; }, 2000);
            } catch(e) { clearInterval(interval); alert('❌ 失敗: ' + e.message); pa.style.display = 'none'; this.disabled = false; }
        };

        function escapeHtml(s) { if (!s) return ''; return s.replace(/[&<>]/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[m])); }
        function formatNumber(n) { if (n >= 100000000) return (n / 100000000).toFixed(1) + '億'; if (n >= 10000) return (n / 10000).toFixed(1) + '万'; return n.toString(); }
        document.getElementById('urlInput').onkeypress = e => { if (e.key === 'Enter') document.getElementById('infoBtn').click(); };
    </script>
</body>
</html>
'''

def sanitize_filename(title):
    name = re.sub(r'[\\/*?:"<>|]', '', title)
    name = re.sub(r'[#%&{}\\[\]~!$^@+/=,]', '_', name)
    name = re.sub(r'_+', '_', name)
    name = name.strip(' ._')[:100]
    return name if name else 'youtube'

def download_thumbnail(url, save_path):
    try:
        urllib.request.urlretrieve(url, save_path)
        return True
    except:
        return False

@app.route('/')
def index():
    return MAIN_HTML

@app.route('/live/<path:video_url>')
def live_page(video_url):
    import urllib.parse
    url = urllib.parse.unquote(video_url)
    try:
        ydl_opts = get_ydl_opts({'extract_flat': True})
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False) or {}
            cnt = info.get('view_count', 0)
            view_str = f"{cnt/10000:.1f}万" if cnt >= 10000 else str(cnt)
            video_id = info.get('id', '')
            title = info.get('title', 'ライブ配信')
            return render_template_string(LIVE_HTML, title=title, view_count=view_str, video_url=url, video_id=video_id)
    except Exception as e:
        return render_template_string(LIVE_HTML, title='ライブ配信', view_count='?', video_url=url, video_id='')

@app.route('/video_info', methods=['POST'])
def video_info():
    data = request.get_json()
    url = data['url']
    if 'youtu.be' in url:
        video_id = url.split('/')[-1].split('?')[0]
        url = f'https://www.youtube.com/watch?v={video_id}'
    
    ydl_opts = get_ydl_opts()
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = []
            for f in info.get('formats', []):
                format_id = str(f['format_id'])
                if '-drc' in format_id:
                    continue
                if f.get('vcodec') != 'none' and f.get('height'):
                    formats.append({
                        'itag': format_id,
                        'height': f['height'],
                        'fps': f.get('fps'),
                        'preview_url': f.get('url', '')
                    })
            formats.sort(key=lambda x: -x['height'])
            
            thumbnails = []
            video_id = info.get('id', '')
            for size in ['default', 'mqdefault', 'hqdefault', 'sddefault', 'maxresdefault']:
                thumb_url = f'https://img.youtube.com/vi/{video_id}/{size}.jpg'
                thumbnails.append({'size': size, 'url': thumb_url})
            
            is_live = info.get('is_live', False) or info.get('live_status') == 'is_live'
            
            return jsonify({
                'success': True,
                'title': info.get('title'),
                'view_count': info.get('view_count', 0),
                'duration': info.get('duration_string'),
                'formats': formats,
                'thumbnails': thumbnails,
                'video_id': video_id,
                'is_live': is_live
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/live_streams', methods=['POST'])
def live_streams():
    data = request.get_json()
    url = data['url']
    ydl_opts = get_ydl_opts({'quiet': True})
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return jsonify({'success': False, 'error': '情報取得失敗'})
            formats = []
            for f in info.get('formats', []):
                if f.get('vcodec') != 'none' and f.get('height'):
                    format_id = str(f['format_id'])
                    if '-drc' not in format_id:
                        formats.append({
                            'itag': format_id,
                            'height': f['height'],
                            'fps': f.get('fps'),
                            'stream_url': f.get('url', '')
                        })
            formats.sort(key=lambda x: -x['height'])
            return jsonify({'success': True, 'formats': formats})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/live_chat', methods=['POST'])
def live_chat():
    data = request.get_json()
    video_id = data.get('video_id')
    last_id = data.get('last_id')
    messages = []
    try:
        url = f'https://www.youtube.com/watch?v={video_id}'
        ydl_opts = get_ydl_opts({'quiet': True, 'getcomments': True})
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info and 'comments' in info and info['comments']:
                for comment in info['comments'][:50]:
                    msg_id = str(comment.get('id', ''))
                    if last_id and msg_id == last_id:
                        continue
                    messages.append({
                        'id': msg_id,
                        'author': comment.get('author', '不明'),
                        'message': comment.get('text', ''),
                    })
                    if len(messages) >= 30:
                        break
        return jsonify({'success': True, 'messages': messages})
    except Exception as e:
        return jsonify({'success': True, 'messages': []})

@app.route('/live_info', methods=['POST'])
def live_info():
    video_id = request.json.get('video_id')
    try:
        url = f'https://www.youtube.com/watch?v={video_id}'
        ydl_opts = get_ydl_opts({'quiet': True})
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return jsonify({'success': False})
            cnt = info.get('view_count', 0)
            return jsonify({'success': True, 'view_count': f"{cnt/10000:.1f}万" if cnt >= 10000 else str(cnt)})
    except:
        return jsonify({'success': False})

@app.route('/download_live', methods=['POST'])
def download_live():
    data = request.get_json()
    url = data['url']
    itag = data['itag']
    title = data.get('title', 'live')
    safe_title = sanitize_filename(title)
    temp_dir = tempfile.mkdtemp(dir=TEMP_BASE)
    output_file = os.path.join(temp_dir, f'{safe_title}.mp4')
    ydl_opts = get_ydl_opts({'format': itag, 'outtmpl': output_file, 'quiet': True, 'retries': 30})
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
        actual_file = output_file
        if not os.path.exists(output_file):
            base = os.path.splitext(output_file)[0]
            for ext in ['.mp4', '.webm', '.mkv']:
                test_path = base + ext
                if os.path.exists(test_path):
                    actual_file = test_path
                    break
        if not os.path.exists(actual_file):
            raise Exception('ファイルが見つかりません')
        with open(actual_file, 'rb') as f:
            file_data = f.read()
        from urllib.parse import quote
        encoded_filename = quote(os.path.basename(actual_file))
        response = Response(file_data, mimetype='video/mp4')
        response.headers['Content-Disposition'] = f"attachment; filename=\"{encoded_filename}\"; filename*=UTF-8''{encoded_filename}"
        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        def cleanup():
            time.sleep(5)
            shutil.rmtree(temp_dir, ignore_errors=True)
        threading.Thread(target=cleanup).start()

@app.route('/download', methods=['POST'])
def download():
    data = request.get_json()
    url = data['url']
    title = data.get('title', 'video')
    download_type = data.get('type', 'video')
    
    if 'youtu.be' in url:
        video_id = url.split('/')[-1].split('?')[0]
        url = f'https://www.youtube.com/watch?v={video_id}'
    
    safe_title = sanitize_filename(title)
    temp_dir = tempfile.mkdtemp(dir=TEMP_BASE)
    
    try:
        if download_type == 'video':
            itag = data.get('itag')
            if not itag:
                return jsonify({'error': '画質が指定されていません'}), 400
            output_template = os.path.join(temp_dir, f'{safe_title}.%(ext)s')
            ydl_opts = get_ydl_opts({
                'format': f'{itag}+bestaudio/best',
                'outtmpl': output_template,
                'merge_output_format': 'mp4',
            })
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
            actual_file = None
            for ext in ['.mp4', '.webm', '.mkv']:
                test_path = os.path.join(temp_dir, f'{safe_title}{ext}')
                if os.path.exists(test_path) and os.path.getsize(test_path) > 10000:
                    actual_file = test_path
                    break
            if not actual_file:
                for ext in ['.mp4', '.webm', '.mkv']:
                    pattern = os.path.join(temp_dir, f'*{ext}')
                    files = glob.glob(pattern)
                    for f in files:
                        if os.path.getsize(f) > 10000:
                            actual_file = f
                            break
                    if actual_file:
                        break
        
        elif download_type == 'audio':
            audio_format = data.get('audio_format', 'mp3')
            output_template = os.path.join(temp_dir, f'{safe_title}.%(ext)s')
            ydl_opts = get_ydl_opts({
                'format': 'bestaudio/best',
                'outtmpl': output_template,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': audio_format,
                    'preferredquality': '192',
                }],
            })
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
            actual_file = None
            for ext in ['.mp3', '.m4a', '.opus', '.wav']:
                test_path = os.path.join(temp_dir, f'{safe_title}{ext}')
                if os.path.exists(test_path) and os.path.getsize(test_path) > 10000:
                    actual_file = test_path
                    break
            if not actual_file:
                for ext in ['.mp3', '.m4a', '.opus', '.wav']:
                    pattern = os.path.join(temp_dir, f'*{ext}')
                    files = glob.glob(pattern)
                    for f in files:
                        if os.path.getsize(f) > 10000:
                            actual_file = f
                            break
                    if actual_file:
                        break
        
        else:  # thumbnail
            size = data.get('size', 'maxresdefault')
            video_id = data.get('video_id', '')
            if not video_id:
                ydl_opts = get_ydl_opts()
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    video_id = info.get('id', '')
            size_map = {'default': 'default', 'mqdefault': 'mqdefault', 'hqdefault': 'hqdefault', 'sddefault': 'sddefault', 'maxresdefault': 'maxresdefault'}
            size_name = size_map.get(size, 'maxresdefault')
            thumb_url = f'https://img.youtube.com/vi/{video_id}/{size_name}.jpg'
            output_file = os.path.join(temp_dir, f'{safe_title}.jpg')
            success = download_thumbnail(thumb_url, output_file)
            if not success:
                thumb_url = f'https://img.youtube.com/vi/{video_id}/hqdefault.jpg'
                success = download_thumbnail(thumb_url, output_file)
            if not success:
                raise Exception('サムネイルが見つかりません')
            actual_file = output_file
        
        if not actual_file or not os.path.exists(actual_file):
            all_files = os.listdir(temp_dir)
            raise Exception(f'出力ファイルが見つかりません: {all_files}')
        
        with open(actual_file, 'rb') as f:
            file_data = f.read()
        
        from urllib.parse import quote
        encoded_filename = quote(os.path.basename(actual_file))
        
        ext = os.path.splitext(actual_file)[1].lower()
        mime_map = {'.mp4': 'video/mp4', '.webm': 'video/webm', '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.opus': 'audio/opus', '.wav': 'audio/wav', '.jpg': 'image/jpeg'}
        mime_type = mime_map.get(ext, 'application/octet-stream')
        
        response = Response(file_data, mimetype=mime_type)
        response.headers['Content-Disposition'] = f"attachment; filename=\"{encoded_filename}\"; filename*=UTF-8''{encoded_filename}"
        return response
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        def cleanup():
            time.sleep(5)
            shutil.rmtree(temp_dir, ignore_errors=True)
        threading.Thread(target=cleanup).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
