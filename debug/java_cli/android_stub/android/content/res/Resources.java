package android.content.res;

/** 编译检查桩（真机签名一致）。 */
public class Resources {
    public static final class DisplayMetrics {
        public float density = 2.0f;
    }

    public DisplayMetrics getDisplayMetrics() { return new DisplayMetrics(); }
}
