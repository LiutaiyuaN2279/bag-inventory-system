package com.bagpurchase.inventory;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.ContentValues;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.print.PrintAttributes;
import android.print.PrintManager;
import android.provider.MediaStore;
import android.util.Base64;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;
import androidx.webkit.WebViewAssetLoader;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;

/**
 * WebView 容器：把打包在 assets/www 里的 Vue 前端跑起来。
 *
 * 关键点：
 * 1) 前端是 ES Module 构建产物（<script type="module">）。用 file:// 加载时
 *    模块脚本会被当作跨域请求拦截，页面直接白屏，所以这里改用
 *    WebViewAssetLoader 把 assets 映射到 https://appassets.androidplatform.net，
 *    拿到正常的 https 源，模块加载、localStorage 等都不会受限。
 * 2) 前端用 createWebHashHistory，路由都是 #/xxx，配合 https 源不会有刷新 404。
 * 3) 后端地址由用户在前端「连接服务器」页填写，请求经 axios 适配器改写到该地址，
 *    因此需要放行明文 http（Android 9+ 默认禁止）；向自己的 https 源发起的请求不受影响。
 * 4) 通过 AndroidBridge 暴露原生能力：保存导出文件、打印单据、原生提示。
 */
public class MainActivity extends AppCompatActivity {

    /** WebViewAssetLoader 映射出的虚拟域名（必须是 https，模块脚本才被当作安全上下文） */
    private static final String APP_ORIGIN = "https://appassets.androidplatform.net";
    private static final String START_URL = APP_ORIGIN + "/index.html";

    private WebView webView;
    private ValueCallback<Uri[]> fileCallback;
    private static final int REQ_FILE_CHOOSER = 1001;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        FrameLayout root = new FrameLayout(this);
        root.setLayoutParams(new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        webView = new WebView(this);
        webView.setLayoutParams(new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        root.addView(webView);
        setContentView(root);

        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(true);
        s.setAllowContentAccess(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        // 布局按屏幕宽度自适应：前端是桌面版 Element Plus 界面，通过缩放适配手机
        s.setSupportZoom(true);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        s.setTextZoom(100);

        webView.addJavascriptInterface(new Bridge(), "AndroidBridge");

        // assets/www 通过虚拟 https 源提供，绕开 file:// 对 ES Module 的跨域拦截
        final WebViewAssetLoader assetLoader = new WebViewAssetLoader.Builder()
                .setDomain("appassets.androidplatform.net")
                .addPathHandler("/", new WebViewAssetLoader.AssetsPathHandler(this))
                .build();

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                return assetLoader.shouldInterceptRequest(request.getUrl());
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                String url = request.getUrl().toString();
                // 本地页面（含 hash 路由）直接放行
                if (url.startsWith(APP_ORIGIN)) return false;
                // 外链（如文档地址）交给系统浏览器
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                } catch (Exception ignored) {
                }
                return true;
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            // 让 <input type=file> / el-upload 能调起系统文件选择器（含拍照）
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                             FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                try {
                    Intent intent = new Intent(Intent.ACTION_GET_CONTENT);
                    intent.addCategory(Intent.CATEGORY_OPENABLE);
                    intent.setType("image/*");
                    Intent chooser = Intent.createChooser(intent, "选择单据照片");
                    startActivityForResult(chooser, REQ_FILE_CHOOSER);
                    return true;
                } catch (Exception e) {
                    fileCallback = null;
                    return false;
                }
            }

            @Override
            public void onPermissionRequest(final PermissionRequest request) {
                runOnUiThread(() -> request.grant(request.getResources()));
            }
        });

        webView.loadUrl(START_URL);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == REQ_FILE_CHOOSER) {
            if (fileCallback != null) {
                Uri[] results = null;
                if (resultCode == Activity.RESULT_OK && data != null) {
                    if (data.getClipData() != null) {
                        int count = data.getClipData().getItemCount();
                        results = new Uri[count];
                        for (int i = 0; i < count; i++) {
                            results[i] = data.getClipData().getItemAt(i).getUri();
                        }
                    } else if (data.getData() != null) {
                        results = new Uri[]{data.getData()};
                    }
                }
                fileCallback.onReceiveValue(results);
                fileCallback = null;
            }
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK && webView != null) {
            // 前端是 hash 路由：有历史记录就返回上一页，否则交给系统退出
            if (webView.canGoBack()) {
                webView.evaluateJavascript(
                        "(function(){try{history.back();return '1';}catch(e){return '0';}})()", null);
                return true;
            }
        }
        return super.onKeyDown(keyCode, event);
    }

    /** 暴露给前端 JS 的原生能力 */
    private class Bridge {

        /** 导出 Excel 等文件：前端把 blob 转 base64 传进来，这里写入「下载」目录 */
        @JavascriptInterface
        public boolean saveBase64File(String filename, String base64, String mime) {
            try {
                byte[] bytes = Base64.decode(base64, Base64.DEFAULT);
                String safeName = (filename == null || filename.trim().isEmpty())
                        ? "export_" + System.currentTimeMillis() : filename.replaceAll("[/\\\\:*?\"<>|]", "_");

                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    ContentValues values = new ContentValues();
                    values.put(MediaStore.Downloads.DISPLAY_NAME, safeName);
                    values.put(MediaStore.Downloads.MIME_TYPE,
                            mime == null || mime.isEmpty() ? "application/octet-stream" : mime);
                    values.put(MediaStore.Downloads.IS_PENDING, 1);
                    Uri uri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
                    if (uri == null) return false;
                    try (OutputStream out = getContentResolver().openOutputStream(uri)) {
                        if (out == null) return false;
                        out.write(bytes);
                    }
                    values.clear();
                    values.put(MediaStore.Downloads.IS_PENDING, 0);
                    getContentResolver().update(uri, values, null, null);
                    return true;
                }

                File dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
                if (!dir.exists() && !dir.mkdirs()) return false;
                File out = new File(dir, safeName);
                try (FileOutputStream fos = new FileOutputStream(out)) {
                    fos.write(bytes);
                }
                return true;
            } catch (Exception e) {
                return false;
            }
        }

        /** 打印单据：交给系统打印服务（可预览、另存 PDF 或连接打印机） */
        @JavascriptInterface
        public void printHtml(final String html) {
            runOnUiThread(() -> {
                try {
                    WebView printer = new WebView(MainActivity.this);
                    printer.getSettings().setJavaScriptEnabled(true);
                    printer.loadDataWithBaseURL(null, html, "text/html", "UTF-8", null);
                    printer.setWebViewClient(new WebViewClient() {
                        @Override
                        public void onPageFinished(WebView view, String url) {
                            try {
                                PrintManager pm = (PrintManager) getSystemService(PRINT_SERVICE);
                                String job = getString(R.string.app_name) + "-单据";
                                pm.print(job, view.createPrintDocumentAdapter(job),
                                        new PrintAttributes.Builder().build());
                            } catch (Exception e) {
                                toast("调起打印失败：" + e.getMessage());
                            }
                        }
                    });
                } catch (Exception e) {
                    toast("打印失败：" + e.getMessage());
                }
            });
        }

        /** 原生提示（WebView 里 console.log 看不到时用） */
        @JavascriptInterface
        public void toast(final String msg) {
            runOnUiThread(() -> Toast.makeText(MainActivity.this, msg, Toast.LENGTH_SHORT).show());
        }

        /** 让前端知道自己在原生容器里（用于显示「连接服务器」入口） */
        @JavascriptInterface
        public String platform() {
            return "android";
        }
    }
}
