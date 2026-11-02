package com.netpractice.app

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.webkit.ValueCallback
import android.widget.Toast
import java.net.HttpURLConnection
import java.net.URL

class FileManager(
    private val activity: Activity,
    private val allowedPort: Int
) {
    private var openCallback: ValueCallback<Array<Uri>>? = null
    private var pendingDownloadUrl: String? = null

    fun openFileChooser(
        callback: ValueCallback<Array<Uri>>,
        acceptTypes: Array<String>?
    ) {
        openCallback?.onReceiveValue(null)
        openCallback = callback
        val mimeTypes = normalizeMimeTypes(acceptTypes)
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "*/*"
            if (mimeTypes.isNotEmpty()) {
                putExtra(Intent.EXTRA_MIME_TYPES, mimeTypes)
            }
        }
        activity.startActivityForResult(intent, REQ_OPEN)
    }

    fun download(url: String) {
        if (!isAllowedDownload(url)) {
            showToast("Скачивание с внешнего адреса заблокировано")
            return
        }
        pendingDownloadUrl = url
        val intent = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = mimeFor(url)
            putExtra(Intent.EXTRA_TITLE, nameFor(url))
        }
        activity.startActivityForResult(intent, REQ_CREATE)
    }

    fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        when (requestCode) {
            REQ_OPEN -> {
                val uri = if (resultCode == Activity.RESULT_OK) data?.data else null
                openCallback?.onReceiveValue(uri?.let { arrayOf(it) })
                openCallback = null
            }
            REQ_CREATE -> {
                val uri = if (resultCode == Activity.RESULT_OK) data?.data else null
                val url = pendingDownloadUrl
                pendingDownloadUrl = null
                if (uri != null && url != null) {
                    saveDownload(url, uri)
                }
            }
        }
    }

    private fun saveDownload(url: String, uri: Uri) {
        if (!isAllowedDownload(url)) {
            showToast("Скачивание с внешнего адреса заблокировано")
            return
        }
        Thread {
            try {
                val connection = URL(url).openConnection() as HttpURLConnection
                connection.connectTimeout = 15000
                connection.readTimeout = 30000
                connection.requestMethod = "GET"
                connection.instanceFollowRedirects = false
                connection.useCaches = false
                try {
                    val code = connection.responseCode
                    check(code in 200..299) { "HTTP $code" }
                    val stream = connection.inputStream
                    val output = activity.contentResolver.openOutputStream(uri)
                        ?: error("Не удалось открыть выбранный файл")
                    stream.use { input -> output.use { target -> input.copyTo(target) } }
                } finally {
                    connection.disconnect()
                }
                showToast("Файл сохранён")
            } catch (error: Exception) {
                showToast("Не удалось сохранить файл: ${error.message}")
            }
        }.start()
    }

    private fun isAllowedDownload(url: String): Boolean {
        val uri = Uri.parse(url)
        return uri.scheme == "http" &&
            uri.host == "127.0.0.1" &&
            uri.port == allowedPort
    }

    private fun normalizeMimeTypes(acceptTypes: Array<String>?): Array<String> {
        val result = linkedSetOf<String>()
        for (raw in acceptTypes.orEmpty()) {
            val value = raw.trim().lowercase()
            when {
                value.isEmpty() -> Unit
                value.endsWith(".nptpack") ||
                    value.endsWith(".zip") ||
                    value == "application/zip" -> {
                    result.add("application/zip")
                    result.add("application/x-zip-compressed")
                    result.add("application/x-zip")
                    result.add("application/octet-stream")
                }
                value.endsWith(".json") ||
                    value == "application/json" ||
                    value == "text/json" -> {
                    result.add("application/json")
                    result.add("text/json")
                    result.add("text/plain")
                    result.add("application/octet-stream")
                }
                value.startsWith("image/") || value.contains("/") -> result.add(value)
            }
        }
        return result.toTypedArray()
    }

    private fun nameFor(url: String): String {
        val path = url.substringBefore('?')
        return when {
            path.contains("/data/export") -> "netpractice_backup.json"
            path.contains("/export") -> "netpractice_module.nptpack"
            else -> "netpractice-download"
        }
    }

    private fun mimeFor(url: String): String {
        val path = url.substringBefore('?')
        return when {
            path.contains("/data/export") -> "application/json"
            path.contains("/export") -> "application/zip"
            else -> "application/octet-stream"
        }
    }

    private fun showToast(message: String) {
        activity.runOnUiThread {
            Toast.makeText(activity, message, Toast.LENGTH_SHORT).show()
        }
    }

    companion object {
        private const val REQ_OPEN = 1001
        private const val REQ_CREATE = 1002
    }
}
