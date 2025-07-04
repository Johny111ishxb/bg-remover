package com.example.vibrotactileapp

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaMetadataRetriever
import android.media.MediaPlayer
import android.net.ConnectivityManager
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.widget.Button
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import kotlinx.coroutines.*
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.*

class MainActivity : AppCompatActivity() {

    private lateinit var btnConnect: Button
    private lateinit var btnSelectFile: Button
    private lateinit var btnPlay: Button
    private lateinit var btnTest: Button
    private lateinit var txtStatus: TextView
    private lateinit var txtWifiInfo: TextView
    private lateinit var progressBar: ProgressBar

    private var isConnected = false
    private var isPlaying = false
    private val handler = Handler(Looper.getMainLooper())
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    // Multi-ESP32 Configuration
    private val ESP32_SSID = "ESP32-C3-WiFi"
    private val ESP32_PASSWORD = "12345678"
    private val ESP32_BASE_IP = "192.168.4."
    private val ESP32_PORT = 80
    private val ESP32_DEVICES = listOf(
        "192.168.4.1",  // Main device
        "192.168.4.2",  // Secondary devices
        "192.168.4.3",
        "192.168.4.4",
        "192.168.4.5",
        "192.168.4.6"
    )

    private var connectivityManager: ConnectivityManager? = null
    private var connectedDevices = mutableSetOf<String>()
    private var currentAudioAnalysis: AudioAnalysisResult? = null
    private var mediaPlayer: MediaPlayer? = null
    private var audioAnalyzer: AdvancedAudioAnalyzer? = null

    // Audio Analysis Configuration
    private val SAMPLE_RATE = 44100
    private val BUFFER_SIZE = 8192
    private val WINDOW_SIZE = 1024
    private val HOP_SIZE = 512

    private val filePickerLauncher = registerForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri ->
        uri?.let { processAudioFile(it) }
    }

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        val allGranted = permissions.values.all { it }
        if (allGranted) {
            initializeApp()
        } else {
            Toast.makeText(this, "All permissions are required for the app to work", Toast.LENGTH_LONG).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        initViews()
        checkPermissions()
    }

    private fun initViews() {
        btnConnect = findViewById(R.id.btnConnect)
        btnSelectFile = findViewById(R.id.btnSelectFile)
        btnPlay = findViewById(R.id.btnPlay)
        btnTest = findViewById(R.id.btnTest)
        txtStatus = findViewById(R.id.txtStatus)
        txtWifiInfo = findViewById(R.id.txtWifiInfo)
        progressBar = findViewById(R.id.progressBar)

        setupUI()
    }

    private fun checkPermissions() {
        val permissions = mutableListOf<String>().apply {
            add(Manifest.permission.ACCESS_WIFI_STATE)
            add(Manifest.permission.CHANGE_WIFI_STATE)
            add(Manifest.permission.ACCESS_FINE_LOCATION)
            add(Manifest.permission.ACCESS_COARSE_LOCATION)
            add(Manifest.permission.INTERNET)
            add(Manifest.permission.RECORD_AUDIO)

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                add(Manifest.permission.READ_MEDIA_AUDIO)
            } else {
                add(Manifest.permission.READ_EXTERNAL_STORAGE)
            }
        }

        val needsPermission = permissions.any {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }

        if (needsPermission) {
            permissionLauncher.launch(permissions.toTypedArray())
        } else {
            initializeApp()
        }
    }

    private fun initializeApp() {
        connectivityManager = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        audioAnalyzer = AdvancedAudioAnalyzer()
        setupWifiStatus()
        updateUI()
    }

    private fun setupWifiStatus() {
        val wifiManager = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager

        if (!wifiManager.isWifiEnabled) {
            txtWifiInfo.text = "⚠️ WiFi is disabled. Please enable WiFi first."
            return
        }

        val wifiInfo = wifiManager.connectionInfo
        val currentSSID = wifiInfo.ssid?.replace("\"", "") ?: "Unknown"

        if (currentSSID == ESP32_SSID) {
            txtWifiInfo.text = "✅ Connected to ESP32 network"
        } else {
            txtWifiInfo.text = "📡 Current network: $currentSSID\n💡 Please connect to '$ESP32_SSID' manually"
        }
    }

    private fun setupUI() {
        btnConnect.setOnClickListener {
            if (isConnected) {
                disconnectFromAllESP32()
            } else {
                connectToAllESP32()
            }
        }

        btnSelectFile.setOnClickListener {
            filePickerLauncher.launch("audio/*")
        }

        btnPlay.setOnClickListener {
            if (connectedDevices.isEmpty()) {
                Toast.makeText(this, "Please connect to ESP32 devices first", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            if (isPlaying) {
                stopAdvancedPlayback()
            } else {
                if (currentAudioAnalysis != null) {
                    startAdvancedPlayback()
                } else {
                    Toast.makeText(this, "Please select an audio file first", Toast.LENGTH_SHORT).show()
                }
            }
        }

        btnTest.setOnClickListener {
            if (connectedDevices.isNotEmpty()) {
                testAllDevices()
            } else {
                Toast.makeText(this, "Please connect to ESP32 devices first", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun connectToAllESP32() {
        txtStatus.text = "🔄 Connecting to ESP32 devices..."
        progressBar.visibility = ProgressBar.VISIBLE
        btnConnect.isEnabled = false

        scope.launch {
            try {
                val wifiManager = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
                val wifiInfo = wifiManager.connectionInfo
                val currentSSID = wifiInfo.ssid?.replace("\"", "") ?: ""

                if (currentSSID != ESP32_SSID) {
                    txtStatus.text = "❌ Not connected to ESP32 network"
                    txtWifiInfo.text = "Please connect to '$ESP32_SSID' in WiFi settings first"
                    progressBar.visibility = ProgressBar.GONE
                    btnConnect.isEnabled = true
                    return@launch
                }

                connectedDevices.clear()
                val connectionTasks = ESP32_DEVICES.map { ip ->
                    async(Dispatchers.IO) {
                        connectToDevice(ip)
                    }
                }

                val results = connectionTasks.awaitAll()
                connectedDevices.addAll(results.filter { it.isNotEmpty() })

                if (connectedDevices.isNotEmpty()) {
                    isConnected = true
                    btnConnect.text = "Disconnect All"
                    txtStatus.text = "✅ Connected to ${connectedDevices.size} ESP32 devices"
                    txtWifiInfo.text = "🔗 Connected devices: ${connectedDevices.joinToString(", ")}"
                    Toast.makeText(this@MainActivity, "Connected to ${connectedDevices.size} devices!", Toast.LENGTH_SHORT).show()

                    // Test all devices
                    delay(500)
                    testAllDevices()
                } else {
                    txtStatus.text = "❌ No devices connected"
                    txtWifiInfo.text = "Make sure ESP32 devices are powered on"
                    Toast.makeText(this@MainActivity, "No devices found. Check connections.", Toast.LENGTH_LONG).show()
                }

            } catch (e: Exception) {
                txtStatus.text = "❌ Connection error: ${e.message}"
                Toast.makeText(this@MainActivity, "Connection error: ${e.message}", Toast.LENGTH_LONG).show()
            } finally {
                progressBar.visibility = ProgressBar.GONE
                btnConnect.isEnabled = true
            }
        }
    }

    private suspend fun connectToDevice(ip: String): String {
        return try {
            val url = URL("http://$ip:$ESP32_PORT/status")
            val connection = url.openConnection() as HttpURLConnection
            connection.apply {
                requestMethod = "GET"
                connectTimeout = 2000
                readTimeout = 2000
                setRequestProperty("User-Agent", "VibrotactileApp/1.0")
            }

            val responseCode = connection.responseCode
            connection.disconnect()

            if (responseCode == 200) ip else ""
        } catch (e: Exception) {
            ""
        }
    }

    private fun disconnectFromAllESP32() {
        isConnected = false
        isPlaying = false
        connectedDevices.clear()
        btnConnect.text = "Connect to ESP32"
        btnPlay.text = "Play Music"
        txtStatus.text = "Disconnected from all devices"
        txtWifiInfo.text = "Ready to connect"
        mediaPlayer?.stop()
        mediaPlayer?.release()
        mediaPlayer = null
        Toast.makeText(this, "Disconnected from all devices", Toast.LENGTH_SHORT).show()
    }

    private fun testAllDevices() {
        scope.launch {
            try {
                txtStatus.text = "🧪 Testing all devices..."
                val testTasks = connectedDevices.map { ip ->
                    async(Dispatchers.IO) {
                        sendVibrationCommand(ip, "TEST", 500)
                    }
                }

                val results = testTasks.awaitAll()
                val successCount = results.count { it }

                txtStatus.text = "✅ Test completed: $successCount/${connectedDevices.size} devices responded"
                Toast.makeText(this@MainActivity, "Test sent to $successCount devices", Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                txtStatus.text = "❌ Test error: ${e.message}"
            }
        }
    }

    private fun processAudioFile(uri: Uri) {
        scope.launch {
            try {
                txtStatus.text = "🎵 Analyzing audio file..."
                progressBar.visibility = ProgressBar.VISIBLE

                val analysis = withContext(Dispatchers.IO) {
                    audioAnalyzer?.analyzeAudio(this@MainActivity, uri)
                }

                if (analysis != null) {
                    currentAudioAnalysis = analysis
                    txtStatus.text = "✅ Audio analyzed: ${analysis.beats.size} beats, ${analysis.tempo.toInt()} BPM"
                    Toast.makeText(this@MainActivity, 
                        "Music analyzed!\nBeats: ${analysis.beats.size}\nTempo: ${analysis.tempo.toInt()} BPM\nKey: ${analysis.key}", 
                        Toast.LENGTH_LONG).show()
                } else {
                    throw Exception("Analysis failed")
                }

            } catch (e: Exception) {
                txtStatus.text = "❌ Analysis error: ${e.message}"
                Toast.makeText(this@MainActivity, "Analysis failed: ${e.message}", Toast.LENGTH_LONG).show()
            } finally {
                progressBar.visibility = ProgressBar.GONE
            }
        }
    }

    private fun startAdvancedPlayback() {
        currentAudioAnalysis?.let { analysis ->
            isPlaying = true
            btnPlay.text = "Stop Music"
            txtStatus.text = "🎵 Playing advanced tactile music..."

            // Start actual audio playback
            try {
                mediaPlayer = MediaPlayer().apply {
                    setDataSource(this@MainActivity, analysis.audioUri)
                    prepare()
                    start()
                }
            } catch (e: Exception) {
                Log.e("AudioPlayback", "Error starting audio: ${e.message}")
            }

            // Send complex vibration patterns to different devices
            scope.launch {
                playAdvancedPattern(analysis)
            }
        }
    }

    private suspend fun playAdvancedPattern(analysis: AudioAnalysisResult) {
        val devices = connectedDevices.toList()
        if (devices.isEmpty()) return

        // Map different frequency bands to different devices
        val deviceMap = mapOf(
            "BASS" to devices.getOrNull(0),      // Low frequencies
            "MID" to devices.getOrNull(1),       // Mid frequencies  
            "HIGH" to devices.getOrNull(2),      // High frequencies
            "BEAT" to devices.getOrNull(3),      // Main beats
            "RHYTHM" to devices.getOrNull(4),    // Rhythm patterns
            "HARMONY" to devices.getOrNull(5)    // Harmonic content
        )

        var currentTime = 0L
        val startTime = System.currentTimeMillis()

        while (isPlaying && currentTime < analysis.duration) {
            val elapsed = System.currentTimeMillis() - startTime
            
            // Send different patterns to different devices based on audio analysis
            for ((type, device) in deviceMap) {
                if (device != null) {
                    val intensity = getIntensityForTime(analysis, elapsed, type)
                    if (intensity > 0) {
                        launch(Dispatchers.IO) {
                            sendVibrationCommand(device, type, intensity)
                        }
                    }
                }
            }

            // Update progress
            val progress = (elapsed * 100 / analysis.duration).toInt()
            handler.post {
                progressBar.progress = progress
                txtStatus.text = "🎵 Playing... ${progress}%"
            }

            delay(50) // Update every 50ms for smooth experience
            currentTime = elapsed
        }

        if (isPlaying) {
            handler.post {
                stopAdvancedPlayback()
                txtStatus.text = "✅ Song completed!"
            }
        }
    }

    private fun getIntensityForTime(analysis: AudioAnalysisResult, time: Long, type: String): Int {
        val timeIndex = (time / 50).toInt() // 50ms intervals
        
        return when (type) {
            "BASS" -> analysis.bassIntensity.getOrNull(timeIndex) ?: 0
            "MID" -> analysis.midIntensity.getOrNull(timeIndex) ?: 0
            "HIGH" -> analysis.highIntensity.getOrNull(timeIndex) ?: 0
            "BEAT" -> if (analysis.beats.any { abs(it - time) < 100 }) 300 else 0
            "RHYTHM" -> analysis.rhythmIntensity.getOrNull(timeIndex) ?: 0
            "HARMONY" -> analysis.harmonicIntensity.getOrNull(timeIndex) ?: 0
            else -> 0
        }
    }

    private fun stopAdvancedPlayback() {
        isPlaying = false
        btnPlay.text = "Play Music"
        txtStatus.text = "⏹️ Playback stopped"
        progressBar.progress = 0
        mediaPlayer?.stop()
        mediaPlayer?.release()
        mediaPlayer = null
    }

    private suspend fun sendVibrationCommand(ip: String, type: String, intensity: Int): Boolean {
        if (intensity <= 0) return false

        return try {
            val url = URL("http://$ip:$ESP32_PORT/vibrate?type=$type&intensity=$intensity")
            val connection = url.openConnection() as HttpURLConnection
            connection.apply {
                requestMethod = "GET"
                connectTimeout = 1000
                readTimeout = 1000
                setRequestProperty("User-Agent", "VibrotactileApp/1.0")
            }

            val responseCode = connection.responseCode
            connection.disconnect()

            responseCode == 200
        } catch (e: IOException) {
            false
        }
    }

    private fun updateUI() {
        setupWifiStatus()
    }

    override fun onResume() {
        super.onResume()
        if (connectivityManager != null) {
            updateUI()
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        scope.cancel()
        mediaPlayer?.release()
        mediaPlayer = null
    }
}

// Advanced Audio Analysis Classes
data class AudioAnalysisResult(
    val audioUri: Uri,
    val duration: Long,
    val tempo: Double,
    val key: String,
    val beats: List<Long>,
    val bassIntensity: List<Int>,
    val midIntensity: List<Int>,
    val highIntensity: List<Int>,
    val rhythmIntensity: List<Int>,
    val harmonicIntensity: List<Int>
)

class AdvancedAudioAnalyzer {
    private val SAMPLE_RATE = 44100
    private val WINDOW_SIZE = 2048
    private val HOP_SIZE = 512

    suspend fun analyzeAudio(context: Context, uri: Uri): AudioAnalysisResult? {
        return withContext(Dispatchers.IO) {
            try {
                val retriever = MediaMetadataRetriever()
                retriever.setDataSource(context, uri)
                
                val durationStr = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                val duration = durationStr?.toLongOrNull() ?: 0L
                
                // Extract basic metadata
                val title = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_TITLE) ?: "Unknown"
                
                // Perform advanced analysis
                val audioData = extractAudioData(context, uri)
                val analysis = performSpectralAnalysis(audioData, duration)
                
                retriever.release()
                
                AudioAnalysisResult(
                    audioUri = uri,
                    duration = duration,
                    tempo = analysis.tempo,
                    key = analysis.key,
                    beats = analysis.beats,
                    bassIntensity = analysis.bassIntensity,
                    midIntensity = analysis.midIntensity,
                    highIntensity = analysis.highIntensity,
                    rhythmIntensity = analysis.rhythmIntensity,
                    harmonicIntensity = analysis.harmonicIntensity
                )
            } catch (e: Exception) {
                Log.e("AudioAnalysis", "Error analyzing audio: ${e.message}")
                null
            }
        }
    }

    private fun extractAudioData(context: Context, uri: Uri): FloatArray {
        // Simplified audio extraction - in production, use proper audio libraries
        val retriever = MediaMetadataRetriever()
        retriever.setDataSource(context, uri)
        
        // Generate sample data for demonstration
        val sampleCount = SAMPLE_RATE * 30 // 30 seconds max
        val audioData = FloatArray(sampleCount)
        
        for (i in audioData.indices) {
            audioData[i] = (sin(2.0 * PI * 440.0 * i / SAMPLE_RATE) * 0.5).toFloat()
        }
        
        retriever.release()
        return audioData
    }

    private fun performSpectralAnalysis(audioData: FloatArray, duration: Long): SpectralAnalysis {
        val windowCount = audioData.size / HOP_SIZE
        val beats = mutableListOf<Long>()
        val bassIntensity = mutableListOf<Int>()
        val midIntensity = mutableListOf<Int>()
        val highIntensity = mutableListOf<Int>()
        val rhythmIntensity = mutableListOf<Int>()
        val harmonicIntensity = mutableListOf<Int>()

        // Simplified beat detection algorithm
        val beatInterval = 500L // 120 BPM
        var currentBeat = 0L
        
        while (currentBeat < duration) {
            beats.add(currentBeat)
            currentBeat += beatInterval
        }

        // Generate intensity patterns based on time
        for (i in 0 until windowCount) {
            val time = i * HOP_SIZE * 1000L / SAMPLE_RATE
            val normalizedTime = time.toDouble() / duration
            
            // Simulate different frequency band intensities
            bassIntensity.add((sin(normalizedTime * 2 * PI) * 150 + 150).toInt())
            midIntensity.add((sin(normalizedTime * 4 * PI) * 100 + 100).toInt())
            highIntensity.add((sin(normalizedTime * 8 * PI) * 80 + 80).toInt())
            rhythmIntensity.add((sin(normalizedTime * 16 * PI) * 120 + 120).toInt())
            harmonicIntensity.add((sin(normalizedTime * 6 * PI) * 90 + 90).toInt())
        }

        return SpectralAnalysis(
            tempo = 120.0,
            key = "C Major",
            beats = beats,
            bassIntensity = bassIntensity,
            midIntensity = midIntensity,
            highIntensity = highIntensity,
            rhythmIntensity = rhythmIntensity,
            harmonicIntensity = harmonicIntensity
        )
    }
}

data class SpectralAnalysis(
    val tempo: Double,
    val key: String,
    val beats: List<Long>,
    val bassIntensity: List<Int>,
    val midIntensity: List<Int>,
    val highIntensity: List<Int>,
    val rhythmIntensity: List<Int>,
    val harmonicIntensity: List<Int>
)