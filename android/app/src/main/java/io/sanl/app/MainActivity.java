package io.sanl.app;

import android.annotation.SuppressLint;
import android.app.DownloadManager;
import android.content.Context;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.KeyEvent;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import androidx.appcompat.app.AppCompatActivity;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;

/**
 * Sanl 安卓壳：加载自建节点池面板。
 * 默认地址 https://lzsanlzhuanhuan.kdns.fr ，可在 assets/config.json 覆盖（url 字段）。
 */
public class MainActivity extends AppCompatActivity {

    private static final String DEFAULT_URL = "https://lzsanlzhuanhuan.kdns.fr";
    private WebView web;
    private SwipeRefreshLayout refresh;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        String url = DEFAULT_URL;
        try {
            org.json.JSONObject cfg = new org.json.JSONObject(
                    readAsset("config.json"));
            url = cfg.optString("url", DEFAULT_URL);
        } catch (Exception ignored) { }

        WebView.setWebContentsDebuggingEnabled(false);
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setSupportZoom(true);
        s.setBuiltInZoomControls(true);
        s.setDisplayZoomControls(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        s.setUserAgentString(s.getUserAgentString() + " SanlApp/1.0");
        CookieManager.getInstance().setAcceptCookie(true);

        setContentView(webLayout());

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest req) {
                Uri u = req.getUrl();
                String scheme = u.getScheme() == null ? "" : u.getScheme();
                // 订阅/代理链接交给外部应用处理
                if (scheme.startsWith("http")) return false;
                try {
                    startActivity(new android.content.Intent(
                            android.content.Intent.ACTION_VIEW, u));
                } catch (Exception ignored) { }
                return true;
            }

            @Override
            public void onPageFinished(WebView v, String u) {
                refresh.setRefreshing(false);
            }
        });

        // 订阅文件下载走系统下载器
        web.setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String u, String ua, String cd, String mime, long len) {
                DownloadManager.Request r = new DownloadManager.Request(Uri.parse(u));
                r.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                r.setTitle("sanl-subscription");
                DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
                if (dm != null) dm.enqueue(r);
            }
        });

        if (savedInstanceState != null) {
            web.restoreState(savedInstanceState);
        } else {
            web.loadUrl(url);
        }
    }

    private android.view.ViewGroup webLayout() {
        android.widget.FrameLayout root = new android.widget.FrameLayout(this);
        refresh = new SwipeRefreshLayout(this);
        refresh.addView(web, new android.widget.FrameLayout.LayoutParams(
                android.view.ViewGroup.LayoutParams.MATCH_PARENT,
                android.view.ViewGroup.LayoutParams.MATCH_PARENT));
        root.addView(refresh, new android.widget.FrameLayout.LayoutParams(
                android.view.ViewGroup.LayoutParams.MATCH_PARENT,
                android.view.ViewGroup.LayoutParams.MATCH_PARENT));
        refresh.setOnRefreshListener(() -> web.reload());
        return root;
    }

    private String readAsset(String name) throws Exception {
        java.io.InputStream in = getAssets().open(name);
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        in.close();
        return out.toString("UTF-8");
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        web.saveState(outState);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK && web != null && web.canGoBack()) {
            web.goBack();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }
}
