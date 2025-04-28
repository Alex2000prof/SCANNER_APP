package com.xcheng.scannere3

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.media.MediaPlayer
import android.os.Bundle
import android.os.RemoteException
import android.util.Log
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import ru.atol.barcodeservice.api.CodeSettings
import ru.atol.barcodeservice.api.ScannerSettings

class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "MainActivity"
        private const val CAMERA_REQUEST_CODE = 100
    }

    private lateinit var webView: WebView
    private var scannerSettings: ScannerSettings? = null

    // (A) MediaPlayer для воспроизведения звуков внутри приложения
    private lateinit var mpSuccess: MediaPlayer
    private lateinit var mpError: MediaPlayer

    // (B) BroadcastReceiver для приёма штрихкодов (BROADCAST_EVENT)
    private val scanReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action == "com.xcheng.scanner.action.BARCODE_DECODING_BROADCAST") {
                val barcodeData = intent.getStringExtra("EXTRA_BARCODE_DECODING_DATA") ?: ""
                val barcodeSym  = intent.getStringExtra("EXTRA_BARCODE_DECODING_SYMBOLE") ?: ""
                Log.d("ScanReceiver", "Barcode: $barcodeData, Sym: $barcodeSym")

                // Прокидываем в WebView JS-функцию window.onBarcodeScanned(...)
                webView.post {
                    val safeData = barcodeData.replace("'", "\\'")
                    val jsCode   = "window.onBarcodeScanned('$safeData');"
                    webView.evaluateJavascript(jsCode, null)
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // 1) Инициализируем WebView
        webView = findViewById(R.id.myWebView)
        webView.settings.javaScriptEnabled = true

        // Подключаем JS-интерфейс, чтобы из HTML вызывать playSuccess()/playError()
        webView.addJavascriptInterface(WebAppInterface(), "AndroidAudio")

        // 2) Настраиваем WebViewClient для переключения символогий по URL
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val url = request?.url.toString()
                Log.d(TAG, "Loading URL = $url")

                when {
                    url.contains("/delete_scan") -> {
                        // В режиме удаления скана включаем QR-коды
                        setSymbologies(code128 = true, qr = true, dataMatrix = false)

                    }

                    url.contains("/delete_box") -> {
                        // В режиме удаления коробки отключаем QR, оставляем Code-128
                        setSymbologies(code128 = true, qr = false, dataMatrix = false)
                    }
                    url.contains("/priemka") -> {
                        setSymbologies(code128 = false, qr = false, dataMatrix = true)
                    }
                    url.contains("/scan_box") -> {
                        setSymbologies(code128 = true, qr = true, dataMatrix = false)
                    }

                    url.contains("/carry") -> {
                        setSymbologies(code128 = true, qr = true, dataMatrix = false)
                    }
                    url.contains("/transfer") -> {
                        setSymbologies(code128 = false, qr = true, dataMatrix = true)
                    }


                    else -> {
                        setSymbologies(code128 = true, qr = false, dataMatrix = false)
                    }
                }
                return false
            }
        }
        webView.loadUrl("http://192.168.1.91:5000")

        // 3) Создаём ScannerSettings (ATOL) и подключаемся к сервису
        scannerSettings = object : ScannerSettings() {
            override fun onServiceConnected() {
                Log.d(TAG, "ScannerSettings onServiceConnected")
                // По умолчанию включаем Code128
                setSymbologies(code128 = true, qr = false, dataMatrix = false)
            }
            override fun onServiceDisconnected() {
                Log.d(TAG, "ScannerSettings onServiceDisconnected")
            }
        }
        scannerSettings?.bindService(this)

        // 4) Разрешение на камеру (если нужно)
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            != PackageManager.PERMISSION_GRANTED
        ) {
            ActivityCompat.requestPermissions(
                this,
                arrayOf(Manifest.permission.CAMERA),
                CAMERA_REQUEST_CODE
            )
        }

        // 5) Инициализируем MediaPlayer
        // Предположим, что success.mp3 и fail.mp3 лежат в res/raw/ (или другой вариант)
        mpSuccess = MediaPlayer.create(this, R.raw.success)
        mpError   = MediaPlayer.create(this, R.raw.fail)
    }

    // (C) Регистрируем/снимаем BroadcastReceiver при переходах
    override fun onResume() {
        super.onResume()
        setScanResultBroadcast() // Переводим ТСД в режим BROADCAST_EVENT
        registerReceiver(scanReceiver, IntentFilter("com.xcheng.scanner.action.BARCODE_DECODING_BROADCAST"))
    }
    override fun onPause() {
        super.onPause()
        unregisterReceiver(scanReceiver)
    }

    override fun onDestroy() {
        super.onDestroy()

        // Освобождаем MediaPlayer
        mpSuccess.release()
        mpError.release()

        // Отключаемся от ScannerService
        scannerSettings?.unbindService(this)
        scannerSettings = null
    }

    // Результат запроса разрешений
    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == CAMERA_REQUEST_CODE && grantResults.isNotEmpty()) {
            if (grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                Log.d(TAG, "Camera permission granted")
            } else {
                Log.e(TAG, "Camera permission denied")
            }
        }
    }
    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack()
        } else {
            // Либо ничего не делайте, чтобы приложение не сворачивалось,
            // либо оставьте вызов super.onBackPressed() для стандартного поведения:
            super.onBackPressed()
        }
    }

    /**
     * Переводим ТСД в режим "BROADCAST_EVENT", чтобы сканы приходили в scanReceiver
     */
    private fun setScanResultBroadcast() {
        val intent = Intent("com.xcheng.scanner.action.CONTROL_DATA_EVENT")
        intent.putExtra("extra_data_event", "BROADCAST_EVENT")
        sendBroadcast(intent)
    }

    /**
     * Включаем/выключаем Code128 / QR / DataMatrix (рефлексией)
     */
    private fun setSymbologies(code128: Boolean, qr: Boolean, dataMatrix: Boolean) {
        try {
            val s = scannerSettings ?: return
            val codeSettings = s.codes as? CodeSettings ?: return

            // Отключаем всё
            codeSettings.disableAll()

            // Code128
            setSymViaReflection(codeSettings.code128.enable, "Code128", code128)
            // QR
            setSymViaReflection(codeSettings.qrcode.enable, "QR", qr)
            // DataMatrix
            setSymViaReflection(codeSettings.datamatrix.enable, "DataMatrix", dataMatrix)

            Log.d(TAG, "Symbologies => code128=$code128, qr=$qr, dataMatrix=$dataMatrix")

        } catch (e: RemoteException) {
            Log.e(TAG, "Error setting symbologies", e)
        } catch (e: Exception) {
            Log.e(TAG, "Reflection error: $e", e)
        }
    }

    /**
     * Универсальная функция вызова setValue(...) рефлексией
     */
    private fun setSymViaReflection(enableProp: Any, label: String, value: Boolean) {
        val method = enableProp.javaClass.methods.find { it.name == "setValue" }
        if (method != null) {
            Log.d("DEBUG", "Invoking setValue($value) for $label via reflection")
            method.invoke(enableProp, value)
            Log.d("DEBUG", "Invoked setValue(...) for $label successfully!")
        } else {
            Log.e("DEBUG", "No 'setValue' method found for $label!")
        }
    }

    /**
     * JS-интерфейс, чтобы из HTML (через window.AndroidAudio) вызывать
     * воспроизведение звука (success/error) внутри приложения.
     */
    inner class WebAppInterface {
        @JavascriptInterface
        fun playSuccess() {
            runOnUiThread {
                if (::mpSuccess.isInitialized) {
                    mpSuccess.seekTo(0)
                    mpSuccess.start()
                }
            }
        }

        @JavascriptInterface
        fun playError() {
            runOnUiThread {
                if (::mpError.isInitialized) {
                    mpError.seekTo(0)
                    mpError.start()
                }
            }
        }
        @JavascriptInterface
        fun setQrEnabled(enabled: Boolean) {
            runOnUiThread {
                // Включаем QR-коды вместе с Code128
                setSymbologies(code128 = true, qr = enabled, dataMatrix = false)
                Log.d(TAG, "QR scanning enabled: $enabled")
            }
        }
    }
}



    


























