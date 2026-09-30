package fr.terrelfe.cockpit;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.os.Bundle;
import android.graphics.Color;
import android.text.InputType;
import android.view.View;
import android.view.WindowManager;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebResourceRequest;
import android.widget.*;
import com.chaquo.python.Python;
import com.chaquo.python.PyObject;
import com.chaquo.python.android.AndroidPlatform;
import org.json.JSONObject;
import java.io.*;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private WebView web;
    private TextView status;
    private Button settingsButton, weatherButton, importButton;
    private PyObject backend;
    private String baseUrl;
    private File root;
    private boolean ready = false;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setBackgroundColor(Color.rgb(6, 17, 27));
        // Keep Android 15 edge-to-edge content outside system bars.
        layout.setOnApplyWindowInsetsListener((v, insets) -> {
            v.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                         insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        LinearLayout bar = new LinearLayout(this);
        settingsButton = button("Réglages", bar, this::settings);
        weatherButton = button("Météo ↻", bar, () -> runOperation("Actualisation météo…", () -> backend.callAttr("update_weather")));
        importButton = button("Excel", bar, () -> {
            Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            intent.setType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            startActivityForResult(intent, 1);
        });
        layout.addView(bar);
        status = new TextView(this);
        status.setTextColor(Color.WHITE);
        status.setPadding(16, 6, 16, 6);
        status.setText("Démarrage du cockpit…");
        layout.addView(status);
        web = new WebView(this);
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setDomStorageEnabled(true);
        web.getSettings().setAllowFileAccess(false);
        web.getSettings().setAllowContentAccess(false);
        web.getSettings().setMixedContentMode(android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return baseUrl == null || !request.getUrl().toString().startsWith(baseUrl + "/");
            }
        });
        layout.addView(web, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(layout);
        setBusy(true);
        worker.execute(() -> {
            try {
                root = new File(getFilesDir(), "cockpit");
                copyAssets("cockpit", root);
                if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
                backend = Python.getInstance().getModule("mobile_backend");
                baseUrl = backend.callAttr("start", root.getAbsolutePath()).toString();
                runOnUiThread(() -> { ready = true; setBusy(false); status.setText("Données locales · mises à jour manuelles"); web.loadUrl(baseUrl + "/"); });
            } catch (Exception e) {
                runOnUiThread(() -> status.setText("Démarrage impossible. Fermez puis relancez l’application."));
            }
        });
    }

    private Button button(String text, LinearLayout parent, Runnable action) {
        Button result = new Button(this);
        result.setText(text);
        result.setTextSize(12);
        result.setOnClickListener(v -> { if (ready) action.run(); });
        parent.addView(result, new LinearLayout.LayoutParams(0, -2, 1));
        return result;
    }
    private void setBusy(boolean busy) {
        settingsButton.setEnabled(!busy); weatherButton.setEnabled(!busy); importButton.setEnabled(!busy);
    }
    private void copyAssets(String source, File target) throws IOException {
        String[] children = getAssets().list(source);
        if (children.length > 0) {
            target.mkdirs();
            for (String child : children) copyAssets(source + "/" + child, new File(target, child));
        } else if (!target.exists() || !(target.getName().endsWith("-data.js") || target.getName().equals("data.js") || target.getName().equals("energy.db") || target.getName().equals("KWH.xlsx"))) {
            target.getParentFile().mkdirs();
            try (InputStream in = getAssets().open(source); OutputStream out = new FileOutputStream(target)) {
                byte[] buffer = new byte[8192]; int count;
                while ((count = in.read(buffer)) != -1) out.write(buffer, 0, count);
            }
        }
    }
    private void settings() {
        try {
            JSONObject saved = new JSONObject(backend.callAttr("read_settings").toString());
            String[] keys = {"MYELECTRICALDATA_TOKEN", "LINKY_PDL", "LINKY_START_DATE", "APSYSTEMS_APP_ID", "APSYSTEMS_APP_SECRET", "APSYSTEMS_SID", "MAPPING_JSON"};
            String[] labels = {"Jeton MyElectricalData", "Numéro PDL Linky", "Début historique (AAAA-MM-JJ)", "APsystems App ID", "APsystems App Secret", "APsystems SID", "Association ECU (JSON : MAIN = toiture, PLUG = Plug & Play)"};
            LinearLayout form = new LinearLayout(this); form.setOrientation(LinearLayout.VERTICAL); form.setPadding(28, 12, 28, 12);
            TextView info = new TextView(this); info.setText("Accès enregistrés uniquement sur ce téléphone. Aucun appel API à l’enregistrement. APsystems se met à jour manuellement et consomme un quota."); form.addView(info);
            EditText[] fields = new EditText[keys.length];
            for (int i = 0; i < keys.length; i++) {
                TextView label = new TextView(this); label.setText(labels[i]); form.addView(label);
                fields[i] = new EditText(this); fields[i].setSingleLine(true);
                fields[i].setInputType(InputType.TYPE_CLASS_TEXT | (i == 0 || i == 4 ? InputType.TYPE_TEXT_VARIATION_PASSWORD : InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS));
                fields[i].setText(i == 6 ? saved.optJSONObject("APSYSTEMS_ECU_MAPPING") == null ? "{}" : saved.optJSONObject("APSYSTEMS_ECU_MAPPING").toString() : saved.optString(keys[i], i == 2 ? "2025-01-01" : ""));
                fields[i].setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
                form.addView(fields[i]);
            }
            ScrollView scroll = new ScrollView(this); scroll.addView(form);
            AlertDialog dialog = new AlertDialog.Builder(this).setTitle("Réglages privés").setView(scroll).setNegativeButton("Annuler", null).setPositiveButton("Enregistrer", null).create();
            dialog.setOnShowListener(v -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(button -> {
                try {
                    JSONObject values = new JSONObject();
                    for (int i = 0; i < keys.length; i++) values.put(keys[i], fields[i].getText().toString().trim());
                    backend.callAttr("save_settings", values.toString());
                    dialog.dismiss(); web.reload(); status.setText("Réglages enregistrés · mises à jour manuelles");
                } catch (Exception e) { Toast.makeText(this, "Champs invalides : vérifiez PDL, jeton, date et mapping ECU.", Toast.LENGTH_LONG).show(); }
            }));
            dialog.show();
        } catch (Exception e) { Toast.makeText(this, "Réglages indisponibles.", Toast.LENGTH_LONG).show(); }
    }
    private void runOperation(String message, Runnable operation) {
        setBusy(true); status.setText(message);
        worker.execute(() -> {
            boolean success;
            try { operation.run(); success = true; } catch (Exception e) { success = false; }
            final boolean done = success;
            runOnUiThread(() -> { if (isDestroyed()) return; setBusy(false); status.setText(done ? "Mise à jour terminée" : "Mise à jour impossible · anciennes données conservées"); if (done) web.reload(); });
        });
    }
    @Override protected void onActivityResult(int request, int result, Intent intent) {
        super.onActivityResult(request, result, intent);
        if (request != 1 || result != RESULT_OK || intent == null || intent.getData() == null) return;
        runOperation("Import du classeur…", () -> {
            File pending = new File(root, "import.xlsx");
            try (InputStream in = getContentResolver().openInputStream(intent.getData()); OutputStream out = new FileOutputStream(pending)) {
                byte[] buffer = new byte[8192]; int count; long total = 0;
                while ((count = in.read(buffer)) != -1) { total += count; if (total > 20 * 1024 * 1024) throw new IOException("Too large"); out.write(buffer, 0, count); }
            } catch (IOException e) { pending.delete(); throw new RuntimeException(e); }
            try { backend.callAttr("import_workbook", pending.getAbsolutePath()); } finally { pending.delete(); }
        });
    }
    @Override public void onBackPressed() { if (web.canGoBack()) web.goBack(); else super.onBackPressed(); }
    @Override protected void onDestroy() { web.destroy(); worker.shutdown(); super.onDestroy(); }
}
