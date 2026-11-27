package android.widget;

import android.content.Context;
import android.view.View;

/** 编译检查桩（真机签名一致）。 */
public class LinearLayout extends View {
    public static final int VERTICAL = 0;
    public static final int HORIZONTAL = 1;

    public LinearLayout(Context c) { super(c); }
    public void setOrientation(int o) { }
    public void setPadding(int l, int t, int r, int b) { }
    public void addView(View v) { }
}
