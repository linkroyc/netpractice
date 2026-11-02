package com.netpractice.app

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowManager
import android.webkit.WebView
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import java.util.concurrent.Executors

class MainActivity : Activity() {
    private lateinit var root: FrameLayout
    private lateinit var progress: ProgressBar
    private lateinit var message: TextView
    private var fileManager: FileManager? = null
    private var webView: WebView? = null
    private var loadFailed = false
    private var serverStarted = false
    private val executor = Executors.newSingleThreadExecutor()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        root = FrameLayout(this)
        root.setBackgroundColor(Color.parseColor("#0b1117"))
        progress = ProgressBar(this).apply {
            isIndeterminate = true
        }
        message = TextView(this).apply {
            setTextColor(Color.parseColor("#9fb0c1"))
            textSize = 16f
            text = "Запускаю NetPractice…"
            gravity = android.view.Gravity.CENTER
            setPadding(48, 24, 48, 48)
        }
        val loading = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = android.view.Gravity.CENTER
        }
        loading.addView(progress)
        loading.addView(
            message,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            )
        )
        root.addView(
            loading,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                android.view.Gravity.CENTER
            )
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.setDecorFitsSystemWindows(false)
            root.setOnApplyWindowInsetsListener { view, insets ->
                val bars = insets.getInsets(
                    WindowInsets.Type.systemBars() or
                        WindowInsets.Type.displayCutout()
                )
                view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
                insets
            }
        }
        window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)
        setContentView(root)
        startPythonServer()
    }

    private fun startPythonServer() {
        if (serverStarted) return
        serverStarted = true
        executor.execute {
            val result = PythonServer.start(applicationContext)
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                result.onSuccess { port ->
                    if (webView == null) {
                        openWebView(port)
                    }
                }.onFailure { error ->
                    showError(
                        "Не удалось запустить локальный сервер.\n" +
                            (error.message ?: error.javaClass.simpleName)
                    )
                }
            }
        }
    }

    private fun openWebView(port: Int) {
        if (webView != null) return
        progress.visibility = View.GONE
        message.visibility = View.GONE
        loadFailed = false
        val files = FileManager(this, port)
        fileManager = files
        val manager = WebViewManager(
            this,
            files,
            port,
            onPageLoaded = {
                if (!loadFailed && !isFinishing) {
                    progress.visibility = View.GONE
                    message.visibility = View.GONE
                }
            },
            onError = { detail ->
                loadFailed = true
                showError("Ошибка загрузки: $detail")
            }
        )
        val view = manager.create()
        view.setBackgroundColor(Color.parseColor("#0b1117"))
        webView = view
        root.addView(
            view,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        )
    }

    private fun showError(detail: String) {
        progress.visibility = View.GONE
        webView?.visibility = View.GONE
        message.visibility = View.VISIBLE
        message.bringToFront()
        message.text = "NetPractice не запустился.\n\n$detail"
        message.setTextColor(Color.parseColor("#ff7b7b"))
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        fileManager?.onActivityResult(requestCode, resultCode, data)
    }

    @Suppress("DEPRECATION")
    override fun onBackPressed() {
        val view = webView
        if (!loadFailed && view != null && view.canGoBack()) {
            view.goBack()
        } else {
            super.onBackPressed()
        }
    }

    override fun onDestroy() {
        webView?.destroy()
        webView = null
        fileManager = null
        executor.shutdown()
        if (isFinishing) {
            PythonServer.stop()
        }
        super.onDestroy()
    }
}
