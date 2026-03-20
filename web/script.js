// LTC Timecode Player & Analyzer JavaScript

class LTCPlayer {
    constructor() {
        this.currentAnalysis = null;
        this.isPlaying = false;
        this.currentPosition = 0;
        this.duration = 0;
        this.currentPage = 0;
        this.itemsPerPage = 50;
        this.playbackTimer = null;
        this.frameRate = 30; // Default frame rate
        this.lastRpcTime = 0;
        this._lastFrameTime = 0;
        this._animationFrame = null;
        this.audioElement = null;
        this.audioBlobUrl = null;
        this.currentFile = null;

        this.init();
    }

    init() {
        this.setupEventListeners();
        this.setupFileDropZone();
        this._createAudioElement();
    }

    _createAudioElement() {
        this.audioElement = document.createElement('audio');
        this.audioElement.style.display = 'none';
        document.body.appendChild(this.audioElement);
    }

    _setAudioSource(blobUrl) {
        if (this.audioBlobUrl) {
            URL.revokeObjectURL(this.audioBlobUrl);
        }
        this.audioBlobUrl = blobUrl;
        this.audioElement.src = blobUrl;
        this.audioElement.load();
    }

    setupEventListeners() {
        // File input
        document.getElementById('fileInput').addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                this.loadFile(e.target.files[0]);
            }
        });

        // Browse button
        document.getElementById('browseBtn').addEventListener('click', async () => {
            this.showLoading(true);
            try {
                const result = await eel.browse_for_file()();
                if (result.success) {
                    // Load the file directly using the full path
                    const loadResult = await eel.load_ltc_file(result.file_path)();
                    if (loadResult.success) {
                        this.currentAnalysis = loadResult.analysis;
                        this.displayFileInfo(
                            { name: loadResult.analysis.filename, size: loadResult.analysis.file_size },
                            loadResult.analysis
                        );
                        this.displayAnalysisResults(loadResult.analysis);

                        // Fetch audio data for playback
                        try {
                            const audioResult = await eel.serve_audio_file()();
                            if (audioResult && audioResult.success && audioResult.audio_data) {
                                this._setAudioSource(audioResult.audio_data);
                            }
                        } catch (audioErr) {
                            console.warn('Could not fetch audio for playback:', audioErr);
                        }

                        await this.generateWaveform();
                        await this.loadTimecodeList();
                        await this.validateSignal();
                        this.showSections();
                        this.showToast('LTC file loaded and analyzed successfully', 'success');
                    } else {
                        this.showToast(loadResult.message, 'error');
                    }
                } else {
                    if (result.message !== "No file selected") {
                        this.showToast(result.message, 'error');
                    }
                }
            } catch (error) {
                console.error('Error browsing for file:', error);
                this.showToast('Error opening file browser', 'error');
            } finally {
                this.showLoading(false);
            }
        });

        // Player controls
        document.getElementById('playPauseBtn').addEventListener('click', () => this.togglePlayback());
        document.getElementById('jumpStartBtn').addEventListener('click', () => this.jumpToStart());
        document.getElementById('jumpEndBtn').addEventListener('click', () => this.jumpToEnd());
        document.getElementById('stepBackBtn').addEventListener('click', () => this.stepFrame(-1));
        document.getElementById('stepForwardBtn').addEventListener('click', () => this.stepFrame(1));

        // Position slider
        document.getElementById('positionSlider').addEventListener('input', (e) => {
            this.seekToPosition(parseFloat(e.target.value));
        });

        // Export button
        document.getElementById('exportBtn').addEventListener('click', () => this.exportReport());

        // Pagination
        document.getElementById('prevPageBtn').addEventListener('click', () => this.changePage(-1));
        document.getElementById('nextPageBtn').addEventListener('click', () => this.changePage(1));
    }

    setupFileDropZone() {
        const dropZone = document.getElementById('fileDropZone');
        const fileInput = document.getElementById('fileInput');

        dropZone.addEventListener('click', () => fileInput.click());

        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });

        dropZone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
        });

        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');

            const files = e.dataTransfer.files;
            if (files.length > 0) {
                this.loadFile(files[0]);
            }
        });
    }

    async loadFile(file) {
        if (!this.isAudioFile(file)) {
            this.showToast('Please select a valid audio file (WAV, AIFF, FLAC)', 'error');
            return;
        }

        this.showLoading(true);

        try {
            // Store the File object for audio playback
            this.currentFile = file;

            // Create blob URL for audio playback from the local File object
            this._setAudioSource(URL.createObjectURL(file));

            // Upload file to backend for LTC analysis
            const result = await this.uploadAndLoadFile(file);

            if (result.success) {
                this.currentAnalysis = result.analysis;
                this.displayFileInfo(file, result.analysis);
                this.displayAnalysisResults(result.analysis);
                await this.generateWaveform();
                await this.loadTimecodeList();
                await this.validateSignal();
                this.showSections();
                this.showToast('LTC file loaded and analyzed successfully', 'success');
            } else {
                this.showToast(result.message, 'error');
            }
        } catch (error) {
            console.error('Error loading file:', error);
            this.showToast('Error loading file. Please try again.', 'error');
        } finally {
            this.showLoading(false);
        }
    }

    async uploadAndLoadFile(file) {
        try {
            // Read file as data URL
            const fileReader = new FileReader();

            return new Promise((resolve, reject) => {
                fileReader.onload = async (event) => {
                    try {
                        const fileData = event.target.result;

                        // First upload the file to the backend
                        const uploadResult = await eel.save_uploaded_file(fileData, file.name)();

                        if (uploadResult.success) {
                            // Now analyze the uploaded file
                            const analysisResult = await eel.load_ltc_file(uploadResult.temp_path)();
                            resolve(analysisResult);
                        } else {
                            resolve(uploadResult);
                        }
                    } catch (error) {
                        reject(error);
                    }
                };

                fileReader.onerror = () => {
                    reject(new Error('Failed to read file'));
                };

                fileReader.readAsDataURL(file);
            });
        } catch (error) {
            console.error('Error uploading file:', error);
            return { success: false, message: 'Failed to upload file' };
        }
    }

    isAudioFile(file) {
        const audioTypes = ['audio/wav', 'audio/x-wav', 'audio/aiff', 'audio/x-aiff', 'audio/flac'];
        const audioExtensions = ['.wav', '.aiff', '.flac'];

        return audioTypes.includes(file.type) ||
               audioExtensions.some(ext => file.name.toLowerCase().endsWith(ext));
    }

    displayFileInfo(file, analysis) {
        document.getElementById('fileName').textContent = file.name;
        document.getElementById('fileDuration').textContent = this.formatDuration(analysis.duration);
        document.getElementById('fileSampleRate').textContent = `${analysis.sample_rate} Hz`;
        document.getElementById('fileSize').textContent = this.formatFileSize(file.size);

        document.getElementById('fileInfo').style.display = 'block';

        this.duration = analysis.duration;
        this.updateTimeLabels();
    }

    displayAnalysisResults(analysis) {
        // Update quality meter
        const qualityPercent = Math.round(analysis.signal_quality * 100);
        const qualityFill = document.getElementById('qualityFill');
        qualityFill.style.width = `${qualityPercent}%`;
        qualityFill.className = 'quality-fill';
        if (qualityPercent < 40) {
            qualityFill.classList.add('quality-low');
        } else if (qualityPercent < 70) {
            qualityFill.classList.add('quality-medium');
        } else {
            qualityFill.classList.add('quality-high');
        }
        document.getElementById('qualityText').textContent = `${qualityPercent}%`;

        // Update analysis cards
        document.getElementById('frameRate').textContent = analysis.frame_rate || 'Unknown';
        document.getElementById('validFrames').textContent = analysis.valid_frames.toLocaleString();
        document.getElementById('syncWords').textContent = analysis.sync_word_count.toLocaleString();

        // Extract frame rate for player
        if (analysis.frame_rate && analysis.frame_rate.includes('fps')) {
            const fps = parseFloat(analysis.frame_rate.match(/[\d.]+/)[0]);
            this.frameRate = fps;
        }

        document.getElementById('analysisSection').style.display = 'block';
    }

    async generateWaveform() {
        try {
            const result = await eel.generate_waveform()();
            if (result.success) {
                document.getElementById('waveformImage').src = result.waveform_image;
                document.getElementById('waveformContainer').style.display = 'block';
            }
        } catch (error) {
            console.error('Error generating waveform:', error);
        }
    }

    async loadTimecodeList(page = 0) {
        try {
            this.currentPage = page;
            const startTime = page * this.itemsPerPage / this.frameRate;

            const result = await eel.get_timecode_list(startTime, this.itemsPerPage)();

            if (result.success) {
                this.displayTimecodeList(result.timecode_list);
                this.updatePagination(result.total_frames);
            }
        } catch (error) {
            console.error('Error loading timecode list:', error);
        }
    }

    displayTimecodeList(timecodeList) {
        const tbody = document.getElementById('timecodeTableBody');
        tbody.innerHTML = '';

        timecodeList.forEach(item => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${this.formatTime(item.timestamp)}</td>
                <td><strong>${item.timecode}</strong></td>
                <td>${item.hours.toString().padStart(2, '0')}</td>
                <td>${item.minutes.toString().padStart(2, '0')}</td>
                <td>${item.seconds.toString().padStart(2, '0')}</td>
                <td>${item.frames.toString().padStart(2, '0')}</td>
                <td>${item.user_bits.map(b => b.toString(16).toUpperCase().padStart(2, '0')).join(' ')}</td>
            `;

            // Make row clickable to seek to that position
            row.style.cursor = 'pointer';
            row.addEventListener('click', () => {
                this.seekToPosition(item.timestamp / this.duration * 100);
            });

            tbody.appendChild(row);
        });

        document.getElementById('timecodeListSection').style.display = 'block';
    }

    updatePagination(totalFrames) {
        const totalPages = Math.ceil(totalFrames / this.itemsPerPage);
        const currentPageNum = this.currentPage + 1;

        document.getElementById('pageInfo').textContent = `Page ${currentPageNum} of ${totalPages}`;
        document.getElementById('prevPageBtn').disabled = this.currentPage === 0;
        document.getElementById('nextPageBtn').disabled = this.currentPage >= totalPages - 1;
    }

    async validateSignal() {
        try {
            const result = await eel.validate_ltc_signal()();

            if (result.success) {
                this.displayValidationResults(result.validation);
                document.getElementById('validationSection').style.display = 'block';
            }
        } catch (error) {
            console.error('Error validating signal:', error);
        }
    }

    displayValidationResults(validation) {
        const statusIndicator = document.getElementById('statusIndicator');

        // Update status indicator
        if (validation.overall_valid) {
            statusIndicator.className = 'status-indicator valid';
            statusIndicator.innerHTML = '<i class="fas fa-check-circle"></i><span>Signal is valid</span>';
        } else {
            statusIndicator.className = 'status-indicator invalid';
            statusIndicator.innerHTML = '<i class="fas fa-exclamation-triangle"></i><span>Signal has issues</span>';
        }

        // Display validation checks
        const checksContainer = document.getElementById('validationChecks');
        checksContainer.innerHTML = '';

        const checkLabels = {
            signal_detected: 'LTC Signal Detected',
            good_quality: 'Good Signal Quality',
            frame_rate_detected: 'Frame Rate Detected',
            continuous_timecode: 'Continuous Timecode',
            low_error_rate: 'Low Error Rate'
        };

        Object.entries(validation.checks).forEach(([check, passed]) => {
            const checkDiv = document.createElement('div');
            checkDiv.className = `validation-check ${passed ? 'pass' : 'fail'}`;
            checkDiv.innerHTML = `
                <i class="fas fa-${passed ? 'check' : 'times'}"></i>
                <span>${checkLabels[check]}</span>
            `;
            checksContainer.appendChild(checkDiv);
        });

        // Display recommendations
        const recommendationsList = document.getElementById('recommendationsList');
        recommendationsList.innerHTML = '';

        validation.recommendations.forEach(rec => {
            const li = document.createElement('li');
            li.textContent = rec;
            recommendationsList.appendChild(li);
        });
    }

    showSections() {
        document.getElementById('playerSection').style.display = 'block';
        this.updateTimecodeDisplay();
    }

    // Player control methods
    togglePlayback() {
        if (this.isPlaying) {
            this.pause();
        } else {
            this.play();
        }
    }

    play() {
        if (!this.currentAnalysis) return;

        this.isPlaying = true;
        this.lastRpcTime = 0;
        document.getElementById('playPauseBtn').innerHTML = '<i class="fas fa-pause"></i> Pause';

        // Start audio playback if available
        if (this.audioElement && this.audioBlobUrl) {
            this.audioElement.currentTime = this.currentPosition;
            this.audioElement.play();
        }

        // Start RAF-based playback loop
        this._lastFrameTime = performance.now();
        this._animationFrame = requestAnimationFrame((t) => this._playbackLoop(t));
    }

    _playbackLoop(timestamp) {
        if (!this.isPlaying) return;

        const delta = (timestamp - this._lastFrameTime) / 1000;
        this._lastFrameTime = timestamp;
        this.currentPosition += delta;

        // Sync with audio element if available and playing
        if (this.audioElement && !this.audioElement.paused && this.audioBlobUrl) {
            this.currentPosition = this.audioElement.currentTime;
        }

        if (this.currentPosition >= this.duration) {
            this.currentPosition = this.duration;
            this.pause();
            return;
        }

        // Throttle RPC calls to ~10/sec
        if (timestamp - this.lastRpcTime > 100) {
            this.lastRpcTime = timestamp;
            this.updateDisplay();
        } else {
            // Still update slider/time labels without RPC
            this._updateSliderAndLabels();
        }

        this._animationFrame = requestAnimationFrame((t) => this._playbackLoop(t));
    }

    _updateSliderAndLabels() {
        if (this.duration > 0) {
            const percentage = (this.currentPosition / this.duration) * 100;
            document.getElementById('positionSlider').value = percentage;
        }
        this.updateTimeLabels();
    }

    pause() {
        this.isPlaying = false;
        document.getElementById('playPauseBtn').innerHTML = '<i class="fas fa-play"></i> Play';

        if (this._animationFrame) {
            cancelAnimationFrame(this._animationFrame);
            this._animationFrame = null;
        }

        // Pause audio playback
        if (this.audioElement && !this.audioElement.paused) {
            this.audioElement.pause();
        }
    }

    jumpToStart() {
        this.currentPosition = 0;
        if (this.audioElement && this.audioBlobUrl) {
            this.audioElement.currentTime = 0;
        }
        this.updateDisplay();
    }

    jumpToEnd() {
        this.currentPosition = this.duration;
        if (this.audioElement && this.audioBlobUrl) {
            this.audioElement.currentTime = this.duration;
        }
        this.updateDisplay();
    }

    stepFrame(direction) {
        const frameTime = 1 / this.frameRate;
        this.currentPosition += direction * frameTime;
        this.currentPosition = Math.max(0, Math.min(this.currentPosition, this.duration));
        if (this.audioElement && this.audioBlobUrl) {
            this.audioElement.currentTime = this.currentPosition;
        }
        this.updateDisplay();
    }

    seekToPosition(percentage) {
        this.currentPosition = (percentage / 100) * this.duration;
        if (this.audioElement && this.audioBlobUrl) {
            this.audioElement.currentTime = this.currentPosition;
        }
        this.updateDisplay();
    }

    async updateDisplay() {
        // Guard against division by zero
        if (this.duration > 0) {
            const percentage = (this.currentPosition / this.duration) * 100;
            document.getElementById('positionSlider').value = percentage;
        }

        // Update time labels
        this.updateTimeLabels();

        // Update timecode display
        await this.updateTimecodeDisplay();
    }

    async updateTimecodeDisplay() {
        try {
            const result = await eel.get_timecode_at_position(this.currentPosition)();

            if (result.success) {
                document.getElementById('timecodeDisplay').textContent = result.timecode.formatted;
            } else {
                // Calculate estimated timecode if no exact match
                const hours = Math.floor(this.currentPosition / 3600);
                const minutes = Math.floor((this.currentPosition % 3600) / 60);
                const seconds = Math.floor(this.currentPosition % 60);
                const frames = Math.floor((this.currentPosition % 1) * this.frameRate);

                document.getElementById('timecodeDisplay').textContent =
                    `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}:${frames.toString().padStart(2, '0')}`;
            }
        } catch (error) {
            console.error('Error updating timecode:', error);
        }
    }

    updateTimeLabels() {
        document.getElementById('currentTime').textContent = this.formatTime(this.currentPosition);
        document.getElementById('totalTime').textContent = this.formatTime(this.duration);
        document.getElementById('audioPosition').textContent = this.formatTime(this.currentPosition, true);
    }

    // Utility methods
    changePage(direction) {
        const newPage = this.currentPage + direction;
        if (newPage >= 0) {
            this.loadTimecodeList(newPage);
        }
    }

    async exportReport() {
        try {
            const result = await eel.export_timecode_report()();

            if (result.success) {
                this.showToast(`Report exported: ${result.filename}`, 'success');
            } else {
                this.showToast(result.message, 'error');
            }
        } catch (error) {
            console.error('Error exporting report:', error);
            this.showToast('Error exporting report', 'error');
        }
    }

    formatTime(seconds, includeMs = false) {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);
        const ms = Math.floor((seconds % 1) * 1000);

        const hh = hours.toString().padStart(2, '0');
        const mm = minutes.toString().padStart(2, '0');
        const ss = secs.toString().padStart(2, '0');

        if (includeMs) {
            const prefix = hours > 0 ? `${hh}:` : '';
            return `${prefix}${mm}:${ss}.${ms.toString().padStart(3, '0')}`;
        } else {
            if (hours > 0) {
                return `${hh}:${mm}:${ss}`;
            }
            return `${mm}:${ss}`;
        }
    }

    formatDuration(seconds) {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);

        if (hours > 0) {
            return `${hours}h ${minutes}m ${secs}s`;
        } else {
            return `${minutes}m ${secs}s`;
        }
    }

    formatFileSize(bytes) {
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        if (bytes === 0) return '0 Bytes';
        const i = Math.floor(Math.log(bytes) / Math.log(1024));
        return Math.round(bytes / Math.pow(1024, i) * 100) / 100 + ' ' + sizes[i];
    }

    showLoading(show) {
        document.getElementById('loadingOverlay').style.display = show ? 'flex' : 'none';
    }

    showToast(message, type = 'info') {
        const toast = document.getElementById('toast');
        toast.textContent = message;
        toast.className = `toast ${type}`;
        toast.classList.add('show');

        setTimeout(() => {
            toast.classList.remove('show');
        }, 5000);
    }
}

// Initialize the application when the page loads
document.addEventListener('DOMContentLoaded', () => {
    window.ltcPlayer = new LTCPlayer();
});

// Handle Eel connection errors
window.addEventListener('error', (e) => {
    if (e.message.includes('eel')) {
        console.error('Eel connection error:', e);
        document.getElementById('toast').textContent = 'Connection error with backend service';
        document.getElementById('toast').className = 'toast error show';
    }
});
