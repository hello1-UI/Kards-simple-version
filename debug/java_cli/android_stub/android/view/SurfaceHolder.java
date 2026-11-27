package android.view;

import android.graphics.Canvas;

public class SurfaceHolder {
    public interface Callback {
        void surfaceCreated(SurfaceHolder h);
        void surfaceChanged(SurfaceHolder h, int f, int w, int ht);
        void surfaceDestroyed(SurfaceHolder h);
    }
    public void addCallback(Callback cb) { }
    public Canvas lockCanvas() { return null; }
    public void unlockCanvasAndPost(Canvas c) { }
}
