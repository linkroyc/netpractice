package com.netpractice.app

import android.content.Context
import android.util.Log
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

object PythonServer {
    private const val TAG = "NetPractice"
    private var port: Int? = null

    @Synchronized
    fun start(context: Context): Result<Int> {
        port?.let { return Result.success(it) }
        return runCatching {
            if (!Python.isStarted()) {
                Python.start(AndroidPlatform(context.applicationContext))
            }
            val dataDir = java.io.File(context.filesDir, "netpractice")
            check(dataDir.exists() || dataDir.mkdirs()) {
                "Не удалось создать каталог данных"
            }
            val tempDir = java.io.File(context.cacheDir, "python-tmp")
            check(tempDir.exists() || tempDir.mkdirs()) {
                "Не удалось создать временный каталог"
            }
            val value = Python.getInstance()
                .getModule("android_entry")
                .callAttr(
                    "start_server",
                    dataDir.absolutePath,
                    java.util.TimeZone.getDefault().id,
                    tempDir.absolutePath
                )
            val startedPort = value.toJava(Integer::class.java).toInt()
            port = startedPort
            startedPort
        }.onFailure {
            Log.e(TAG, "Python/Flask startup failed", it)
        }
    }

    @Synchronized
    fun stop() {
        if (!Python.isStarted()) return
        runCatching {
            Python.getInstance()
                .getModule("android_entry")
                .callAttr("stop_server")
        }.onFailure {
            Log.e(TAG, "Python/Flask shutdown failed", it)
        }
        port = null
    }
}
