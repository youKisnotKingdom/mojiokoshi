/**
 * Mojiokoshi Audio Recorder
 * Handles browser audio recording with chunk-based upload and real-time transcription
 */

class AudioRecorder {
    constructor() {
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.initChunk = null;  // webm 初期化セグメント（ヘッダー）
        this.isRecording = false;
        this.isPaused = false;
        this.sessionId = null;
        this.chunkIndex = 0;
        this.startTime = null;
        this.pausedTime = 0;
        this.timerInterval = null;
        this.ws = null;
        this.chunkInterval = 10000; // 10 seconds

        // DOM elements
        this.timerEl = document.getElementById('timer');
        this.statusEl = document.getElementById('status');
        this.btnRecord = document.getElementById('btn-record');
        this.btnPause = document.getElementById('btn-pause');
        this.btnResume = document.getElementById('btn-resume');
        this.btnStop = document.getElementById('btn-stop');
        this.connectionDot = document.getElementById('connection-dot');
        this.connectionText = document.getElementById('connection-text');
        this.chunkInfo = document.getElementById('chunk-info');
        this.chunkCount = document.getElementById('chunk-count');
        this.transcriptionOutput = document.getElementById('transcription-output');
        this.recoveryNotice = document.getElementById('recovery-notice');

        // Check for existing session
        this.checkExistingSession();
    }

    checkExistingSession() {
        const savedSession = localStorage.getItem('recording_session');
        if (savedSession) {
            this.recoveryNotice.classList.remove('hidden');
        }
    }

    async start() {
        try {
            // Request microphone access
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

            // Create MediaRecorder (ブラウザ互換のmimeTypeを選択)
            const mimeType = [
                'audio/webm;codecs=opus',
                'audio/webm',
                'audio/ogg;codecs=opus',
                'audio/mp4',
            ].find(t => MediaRecorder.isTypeSupported(t)) || '';
            this.mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType: mimeType } : {});

            // Handle data available
            this.mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    // 最初のチャンクは webm ヘッダーを含む初期化セグメント
                    if (this.initChunk === null) {
                        this.initChunk = event.data;
                    } else {
                        this.audioChunks.push(event.data);
                    }
                }
            };

            // Start recording
            this.mediaRecorder.start(1000); // Collect data every second
            this.isRecording = true;
            this.isPaused = false;
            this.startTime = Date.now();
            this.pausedTime = 0;
            this.chunkIndex = 0;

            // Generate session ID
            this.sessionId = crypto.randomUUID();
            localStorage.setItem('recording_session', JSON.stringify({
                sessionId: this.sessionId,
                startTime: this.startTime
            }));

            // Connect WebSocket
            this.connectWebSocket();

            // Start timer
            this.startTimer();

            // Schedule chunk uploads
            this.scheduleChunkUpload();

            // Update UI
            this.updateUI('recording');
            this.updateStatus('録音中...');

        } catch (error) {
            console.error('Error starting recording:', error);
            this.updateStatus('エラー: ' + error.message);
        }
    }

    pause() {
        if (this.mediaRecorder && this.isRecording && !this.isPaused) {
            this.mediaRecorder.pause();
            this.isPaused = true;
            this.pausedTime = Date.now();
            this.updateUI('paused');
            this.updateStatus('一時停止中');
        }
    }

    resume() {
        if (this.mediaRecorder && this.isRecording && this.isPaused) {
            this.mediaRecorder.resume();
            const pauseDuration = Date.now() - this.pausedTime;
            this.startTime += pauseDuration;
            this.isPaused = false;
            this.updateUI('recording');
            this.updateStatus('録音中...');
        }
    }

    async stop() {
        if (!this.mediaRecorder || !this.isRecording) return;

        return new Promise((resolve) => {
            this.mediaRecorder.onstop = async () => {
                // Upload final chunk
                await this.uploadChunk(true);

                // Stop all tracks
                this.mediaRecorder.stream.getTracks().forEach(track => track.stop());

                // Clear timer
                if (this.timerInterval) {
                    clearInterval(this.timerInterval);
                }

                // Close WebSocket
                if (this.ws) {
                    this.ws.close();
                }

                // Clear session
                localStorage.removeItem('recording_session');

                this.isRecording = false;
                this.isPaused = false;
                this.updateUI('stopped');
                this.updateStatus('録音を保存しました');

                resolve();
            };

            this.mediaRecorder.stop();
        });
    }

    connectWebSocket() {
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${wsProtocol}//${window.location.host}/ws/recording/${this.sessionId}`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            this.updateConnectionStatus(true);
        };

        this.ws.onclose = () => {
            this.updateConnectionStatus(false);
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.updateConnectionStatus(false);
        };

        this.ws.onmessage = (event) => {
            const message = JSON.parse(event.data);
            this.handleWSMessage(message);
        };
    }

    handleWSMessage(message) {
        switch (message.type) {
            case 'chunk_received':
                this.chunkCount.textContent = message.chunk_index + 1;
                this.chunkInfo.classList.remove('hidden');
                break;

            case 'transcription':
                this.appendTranscription(message.text, message.is_partial);
                break;

            case 'error':
                console.error('Server error:', message.message);
                this.updateStatus('エラー: ' + message.message);
                break;
        }
    }

    appendTranscription(text, isPartial) {
        // Remove placeholder text
        const placeholder = this.transcriptionOutput.querySelector('.italic');
        if (placeholder) {
            placeholder.remove();
        }

        // Find or create current segment
        let currentSegment = this.transcriptionOutput.querySelector('.partial');
        if (isPartial) {
            if (!currentSegment) {
                currentSegment = document.createElement('span');
                currentSegment.className = 'partial text-gray-400';
                this.transcriptionOutput.appendChild(currentSegment);
            }
            currentSegment.textContent = text;
        } else {
            // Finalize partial segment
            if (currentSegment) {
                currentSegment.remove();
            }
            const finalSegment = document.createElement('span');
            finalSegment.className = 'text-gray-700';
            finalSegment.textContent = text + ' ';
            this.transcriptionOutput.appendChild(finalSegment);
        }

        // Auto-scroll
        this.transcriptionOutput.scrollTop = this.transcriptionOutput.scrollHeight;
    }

    scheduleChunkUpload() {
        setInterval(() => {
            if (this.isRecording && !this.isPaused && this.audioChunks.length > 0) {
                this.uploadChunk(false);
            }
        }, this.chunkInterval);
    }

    async uploadChunk(isFinal) {
        if (this.audioChunks.length === 0 && !isFinal) return;

        // 初期化セグメント（ヘッダー）を先頭に付加して有効な webm ファイルにする
        const parts = this.initChunk
            ? [this.initChunk, ...this.audioChunks]
            : [...this.audioChunks];
        const blob = new Blob(parts, { type: 'audio/webm' });
        this.audioChunks = [];

        // Send via WebSocket if connected
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            const reader = new FileReader();
            reader.onload = () => {
                this.ws.send(JSON.stringify({
                    type: 'chunk',
                    chunk_index: this.chunkIndex,
                    is_final: isFinal,
                    data: reader.result.split(',')[1] // Base64 data
                }));
                this.chunkIndex++;
            };
            reader.readAsDataURL(blob);
        } else {
            // Fallback: save to IndexedDB for later upload
            await this.saveToIndexedDB(blob);
        }
    }

    async saveToIndexedDB(blob) {
        // Simplified IndexedDB storage for offline support
        const db = await this.openDB();
        const tx = db.transaction('chunks', 'readwrite');
        const store = tx.objectStore('chunks');
        await store.add({
            sessionId: this.sessionId,
            chunkIndex: this.chunkIndex,
            data: blob,
            timestamp: Date.now()
        });
        this.chunkIndex++;
    }

    async openDB() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open('mojiokoshi', 1);
            request.onerror = () => reject(request.error);
            request.onsuccess = () => resolve(request.result);
            request.onupgradeneeded = (event) => {
                const db = event.target.result;
                if (!db.objectStoreNames.contains('chunks')) {
                    db.createObjectStore('chunks', { keyPath: ['sessionId', 'chunkIndex'] });
                }
            };
        });
    }

    startTimer() {
        this.timerInterval = setInterval(() => {
            if (!this.isPaused) {
                const elapsed = Date.now() - this.startTime;
                this.timerEl.textContent = this.formatTime(elapsed);
            }
        }, 100);
    }

    formatTime(ms) {
        const totalSeconds = Math.floor(ms / 1000);
        const hours = Math.floor(totalSeconds / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);
        const seconds = totalSeconds % 60;
        return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }

    updateUI(state) {
        switch (state) {
            case 'recording':
                this.btnRecord.classList.add('hidden');
                this.btnPause.classList.remove('hidden');
                this.btnResume.classList.add('hidden');
                this.btnStop.classList.remove('hidden');
                break;
            case 'paused':
                this.btnRecord.classList.add('hidden');
                this.btnPause.classList.add('hidden');
                this.btnResume.classList.remove('hidden');
                this.btnStop.classList.remove('hidden');
                break;
            case 'stopped':
                this.btnRecord.classList.remove('hidden');
                this.btnPause.classList.add('hidden');
                this.btnResume.classList.add('hidden');
                this.btnStop.classList.add('hidden');
                break;
        }
    }

    updateStatus(text) {
        this.statusEl.textContent = text;
    }

    updateConnectionStatus(connected) {
        if (connected) {
            this.connectionDot.classList.remove('bg-gray-400', 'bg-red-400');
            this.connectionDot.classList.add('bg-green-400');
            this.connectionText.textContent = '接続済み';
        } else {
            this.connectionDot.classList.remove('bg-gray-400', 'bg-green-400');
            this.connectionDot.classList.add('bg-red-400');
            this.connectionText.textContent = '切断';
        }
    }
}

// Global recorder instance
let recorder = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    recorder = new AudioRecorder();
});

// Global functions for button onclick handlers
function startRecording() {
    if (recorder) recorder.start();
}

function pauseRecording() {
    if (recorder) recorder.pause();
}

function resumeRecording() {
    if (recorder) recorder.resume();
}

function stopRecording() {
    if (recorder) recorder.stop();
}

function recoverSession() {
    // TODO: Implement session recovery
    document.getElementById('recovery-notice').classList.add('hidden');
}

function discardSession() {
    localStorage.removeItem('recording_session');
    document.getElementById('recovery-notice').classList.add('hidden');
}
