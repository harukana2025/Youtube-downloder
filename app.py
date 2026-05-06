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

TEMP_BASE = os.path.join(tempfile.gettempdir(), 'youtube_dl_temp')
os.makedirs(TEMP_BASE, exist_ok=True)

# 環境変数からクッキーを読み込み（Render.com用）
COOKIE_CONTENT = os.environ.get('YOUTUBE_COOKIES', '')
COOKIE_FILE = None

if COOKIE_CONTENT:
    temp_cookie = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt')
    temp_cookie.write(COOKIE_CONTENT)
    temp_cookie.close()
    COOKIE_FILE = temp_cookie.name
    print("🍪 環境変数からクッキーを読み込みました")

def get_ydl_opts(extra_opts=None):
    opts = {
        'quiet': True,
        'no_warnings': False,
        'retries': 30,
    }
    if COOKIE_FILE and os.path.exists(COOKIE_FILE):
        opts['cookiefile'] = COOKIE_FILE
    if extra_opts:
        opts.update(extra_opts)
    return opts

# シンプルなHTML
HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>YouTube Downloader</title>
    <style>
        body { font-family: Arial; max-width: 800px; margin: 50px auto; padding: 20px; }
        input, select, button { width: 100%; padding: 10px; margin: 10px 0; }
        .info { background: #f0f0f0; padding: 15px; border-radius: 5px; margin-top: 20px; }
        .error { color: red; }
        .success { color: green; }
    </style>
</head>
<body>
    <h1>YouTube Downloader</h1>
    <input type="text" id="url" placeholder="YouTube URL">
    <button onclick="fetchInfo()">Get Info</button>
    <div id="result"></div>
    <div id="download-area" style="display:none">
        <select id="quality"></select>
        <button onclick="downloadVideo()">Download</button>
    </div>
    <div id="message"></div>

    <script>
        let formats = [];
        let selectedItag = null;
        let currentUrl = '';

        async function fetchInfo() {
            const url = document.getElementById('url').value;
            if (!url) { alert('Enter URL'); return; }
            currentUrl = url;
            document.getElementById('result').innerHTML = 'Loading...';
            try {
                const res = await fetch('/video_info', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url })
                });
                const data = await res.json();
                if (data.success) {
                    formats = data.formats;
                    document.getElementById('result').innerHTML = `
                        <div class="info">
                            <strong>${escapeHtml(data.title)}</strong><br>
                            Views: ${data.view_count}<br>
                            Duration: ${data.duration}
                        </div>
                    `;
                    const qs = document.getElementById('quality');
                    qs.innerHTML = '';
                    for (let f of formats) {
                        const opt = document.createElement('option');
                        opt.value = f.itag;
                        opt.textContent = f.height + 'p';
                        qs.appendChild(opt);
                    }
                    document.getElementById('download-area').style.display = 'block';
                } else {
                    document.getElementById('result').innerHTML = `<div class="error">Error: ${data.error}</div>`;
                }
            } catch(e) {
                document.getElementById('result').innerHTML = `<div class="error">Error: ${e.message}</div>`;
            }
        }

        async function downloadVideo() {
            const qs = document.getElementById('quality');
            selectedItag = parseInt(qs.value);
            if (!selectedItag) { alert('Select quality'); return; }
            const btn = event.target;
            btn.disabled = true;
            btn.textContent = 'Downloading...';
            try {
                const res = await fetch('/download', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: currentUrl, itag: selectedItag })
                });
                if (!res.ok) { const err = await res.json(); throw new Error(err.error); }
                const blob = await res.blob();
                const a = document.createElement('a');
                const url = URL.createObjectURL(blob);
                a.href = url;
                a.download = 'video.mp4';
                a.click();
                URL.revokeObjectURL(url);
                document.getElementById('message').innerHTML = '<div class="success">Download complete!</div>';
            } catch(e) {
                document.getElementById('message').innerHTML = `<div class="error">Error: ${e.message}</div>`;
            } finally {
                btn.disabled = false;
                btn.textContent = 'Download';
            }
        }

        function escapeHtml(s) {
            if (!s) return '';
            return s.replace(/[&<>]/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[m]));
        }
    </script>
</body>
</html>
'''

def sanitize_filename(title):
    name = re.sub(r'[\\/*?:"<>|]', '', title)
    name = re.sub(r'[#%&{}\\[\]~!$^@+/=,]', '_', name)
    name = re.sub(r'_+', '_', name)
    name = name.strip(' ._')[:100]
    return name if name else 'video'

@app.route('/')
def index():
    return HTML

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
                    })
            formats.sort(key=lambda x: -x['height'])
            return jsonify({
                'success': True,
                'title': info.get('title'),
                'view_count': info.get('view_count', 0),
                'duration': info.get('duration_string'),
                'formats': formats,
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/download', methods=['POST'])
def download():
    data = request.get_json()
    url = data['url']
    itag = data.get('itag')
    
    if not itag:
        return jsonify({'error': 'No format selected'}), 400
    
    temp_dir = tempfile.mkdtemp()
    output_template = os.path.join(temp_dir, 'video.%(ext)s')
    
    ydl_opts = get_ydl_opts({
        'format': f'{itag}+bestaudio/best',
        'outtmpl': output_template,
        'merge_output_format': 'mp4',
    })
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
        
        actual_file = None
        for ext in ['.mp4', '.webm', '.mkv']:
            test_path = os.path.join(temp_dir, f'video{ext}')
            if os.path.exists(test_path):
                actual_file = test_path
                break
        
        if not actual_file:
            files = glob.glob(os.path.join(temp_dir, '*'))
            for f in files:
                if os.path.getsize(f) > 10000:
                    actual_file = f
                    break
        
        if not actual_file:
            raise Exception('Output file not found')
        
        with open(actual_file, 'rb') as f:
            file_data = f.read()
        
        response = Response(file_data, mimetype='video/mp4')
        response.headers['Content-Disposition'] = 'attachment; filename="video.mp4"'
        return response
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        def cleanup():
            time.sleep(5)
            shutil.rmtree(temp_dir, ignore_errors=True)
        threading.Thread(target=cleanup).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
