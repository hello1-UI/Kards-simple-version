package android.app;

import android.content.Context;
import android.os.Bundle;
import android.view.View;

public class Activity extends Context {
    protected void onCreate(Bundle b) { }
    public void setContentView(View v) { }
    public void finish() { }
    public android.content.res.AssetManager getAssets() { return null; }
    public android.content.res.Resources getResources() { return null; }
    public void runOnUiThread(Runnable r) { }
    public void onBackPressed() { }
}
