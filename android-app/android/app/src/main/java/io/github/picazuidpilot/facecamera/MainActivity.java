package io.github.picazuidpilot.facecamera;

import android.os.Bundle;
import android.view.WindowManager;

import androidx.activity.OnBackPressedCallback;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(MediaSaverPlugin.class);
        super.onCreate(savedInstanceState);
        // Scherm niet laten uitgaan tijdens het filmen
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        // Terugknop: eerst de app laten beslissen (paneel sluiten, opname stoppen)
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                if (getBridge() == null || getBridge().getWebView() == null) {
                    finish();
                    return;
                }
                getBridge().getWebView().evaluateJavascript(
                        "(window.__faBack && window.__faBack()) ? 'handled' : 'exit'",
                        (value) -> {
                            if (!"\"handled\"".equals(value)) finish();
                        });
            }
        });
    }
}
