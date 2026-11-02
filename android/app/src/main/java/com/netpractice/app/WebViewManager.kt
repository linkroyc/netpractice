package com.netpractice.app

import android.annotation.SuppressLint
import android.app.Activity
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import java.io.ByteArrayInputStream

@SuppressLint("SetJavaScriptEnabled")
class WebViewManager(
    private val activity: Activity,
    private val fileManager: FileManager,
    private val port: Int,
    private val onPageLoaded: () -> Unit,
    private val onError: (String) -> Unit
) {
    private val baseUrl = "http://127.0.0.1:$port"

    fun create(): WebView {
        val webView = WebView(activity)
        WebView.setWebContentsDebuggingEnabled(false)
        webView.setBackgroundColor(Color.parseColor("#0b1117"))
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            // SAF file picker returns content:// URIs for uploads; navigation and
            // resource loading are still restricted to the loopback server.
            allowContentAccess = true
            javaScriptCanOpenWindowsAutomatically = false
            mediaPlaybackRequiresUserGesture = true
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            builtInZoomControls = false
            displayZoomControls = false
            loadWithOverviewMode = true
            useWideViewPort = true
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                isAlgorithmicDarkeningAllowed = false
            } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                @Suppress("DEPRECATION")
                forceDark = WebSettings.FORCE_DARK_OFF
            }
        }
        webView.isVerticalScrollBarEnabled = true
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView?,
                request: WebResourceRequest?
            ): Boolean {
                val url = request?.url?.toString() ?: return true
                return !isAllowed(url)
            }

            @Deprecated("Deprecated in Java")
            override fun shouldOverrideUrlLoading(view: WebView?, url: String?): Boolean {
                return url == null || !isAllowed(url)
            }

            override fun shouldInterceptRequest(
                view: WebView?,
                request: WebResourceRequest?
            ): WebResourceResponse? {
                val url = request?.url?.toString() ?: return blocked()
                return if (isAllowedResource(url)) null else blocked()
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                onPageLoaded()
            }

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?
            ) {
                super.onReceivedError(view, request, error)
                if (request?.isForMainFrame == true) {
                    onError(error?.description?.toString() ?: "Ошибка загрузки страницы")
                }
            }
        }
        webView.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                webView: WebView?,
                filePathCallback: android.webkit.ValueCallback<Array<android.net.Uri>>?,
                fileChooserParams: FileChooserParams?
            ): Boolean {
                if (filePathCallback == null) return false
                fileManager.openFileChooser(
                    filePathCallback,
                    fileChooserParams?.acceptTypes
                )
                return true
            }
        }
        webView.setDownloadListener { url, _, _, _, _ ->
            fileManager.download(url)
        }
        webView.loadUrl("$baseUrl/")
        return webView
    }

    private fun isAllowed(url: String): Boolean {
        if (url == "about:blank") return true
        val uri = Uri.parse(url)
        return uri.scheme == "http" &&
            uri.host == "127.0.0.1" &&
            uri.port == port
    }

    private fun isAllowedResource(url: String): Boolean {
        return isAllowed(url) || url.startsWith("data:") || url.startsWith("blob:")
    }

    private fun blocked(): WebResourceResponse {
        return WebResourceResponse(
            "text/plain",
            "utf-8",
            403,
            "Forbidden",
            emptyMap(),
            ByteArrayInputStream(ByteArray(0))
        )
    }
}
