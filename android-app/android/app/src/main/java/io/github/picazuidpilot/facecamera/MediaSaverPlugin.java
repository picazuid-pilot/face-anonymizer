package io.github.picazuidpilot.facecamera;

import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Intent;
import android.net.Uri;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.Base64;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.OutputStream;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/**
 * Bewaart foto's en video's in de galerij (Pictures/FA Camera en Movies/FA Camera)
 * en deelt ze. Grote video's komen in stukjes binnen, zodat het geheugen niet volloopt.
 * Vanaf Android 10 is hiervoor geen opslagtoestemming nodig.
 */
@CapacitorPlugin(name = "MediaSaver")
public class MediaSaverPlugin extends Plugin {
    private static final String FOLDER = "FA Camera";

    private static class Pending {
        Uri uri;
        OutputStream out;
    }

    private final Map<String, Pending> pending = new HashMap<>();

    @PluginMethod
    public void begin(PluginCall call) {
        String name = call.getString("name", "anoniem");
        String mime = call.getString("mime", "application/octet-stream");
        boolean video = mime.startsWith("video/");
        ContentResolver resolver = getContext().getContentResolver();
        ContentValues values = new ContentValues();
        values.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
        values.put(MediaStore.MediaColumns.MIME_TYPE, mime);
        values.put(MediaStore.MediaColumns.RELATIVE_PATH,
                (video ? Environment.DIRECTORY_MOVIES : Environment.DIRECTORY_PICTURES) + "/" + FOLDER);
        values.put(MediaStore.MediaColumns.IS_PENDING, 1);
        Uri collection = video
                ? MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
                : MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY);
        try {
            Uri uri = resolver.insert(collection, values);
            if (uri == null) throw new IllegalStateException("Galerij niet beschikbaar");
            Pending p = new Pending();
            p.uri = uri;
            p.out = resolver.openOutputStream(uri);
            if (p.out == null) throw new IllegalStateException("Bestand kon niet geopend worden");
            String id = UUID.randomUUID().toString();
            synchronized (pending) { pending.put(id, p); }
            JSObject ret = new JSObject();
            ret.put("id", id);
            call.resolve(ret);
        } catch (Exception e) {
            call.reject("Bewaren mislukt: " + e.getMessage(), e);
        }
    }

    @PluginMethod
    public void append(PluginCall call) {
        Pending p;
        synchronized (pending) { p = pending.get(call.getString("id", "")); }
        if (p == null) { call.reject("Onbekende opname"); return; }
        try {
            p.out.write(Base64.decode(call.getString("data", ""), Base64.DEFAULT));
            call.resolve();
        } catch (Exception e) {
            call.reject("Schrijven mislukt: " + e.getMessage(), e);
        }
    }

    @PluginMethod
    public void finish(PluginCall call) {
        Pending p;
        synchronized (pending) { p = pending.remove(call.getString("id", "")); }
        if (p == null) { call.reject("Onbekende opname"); return; }
        try {
            p.out.close();
            ContentValues values = new ContentValues();
            values.put(MediaStore.MediaColumns.IS_PENDING, 0);
            getContext().getContentResolver().update(p.uri, values, null, null);
            JSObject ret = new JSObject();
            ret.put("uri", p.uri.toString());
            call.resolve(ret);
        } catch (Exception e) {
            call.reject("Afronden mislukt: " + e.getMessage(), e);
        }
    }

    @PluginMethod
    public void cancel(PluginCall call) {
        Pending p;
        synchronized (pending) { p = pending.remove(call.getString("id", "")); }
        if (p != null) {
            try { p.out.close(); } catch (Exception ignored) { }
            try { getContext().getContentResolver().delete(p.uri, null, null); } catch (Exception ignored) { }
        }
        call.resolve();
    }

    @PluginMethod
    public void share(PluginCall call) {
        String uri = call.getString("uri");
        String mime = call.getString("mime", "*/*");
        if (uri == null) { call.reject("Geen bestand"); return; }
        Intent send = new Intent(Intent.ACTION_SEND);
        send.setType(mime);
        send.putExtra(Intent.EXTRA_STREAM, Uri.parse(uri));
        send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        Intent chooser = Intent.createChooser(send, "Delen");
        chooser.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        getActivity().runOnUiThread(() -> {
            try {
                getActivity().startActivity(chooser);
                call.resolve();
            } catch (Exception e) {
                call.reject("Delen mislukt: " + e.getMessage(), e);
            }
        });
    }
}
