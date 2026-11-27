package android.app;

import android.content.Context;
import android.content.DialogInterface;
import android.view.View;

/** 编译检查桩（真机签名一致：Builder 链式 + create/show）。 */
public class AlertDialog implements DialogInterface {
    public static final int BUTTON_POSITIVE = DialogInterface.BUTTON_POSITIVE;
    public static final int BUTTON_NEGATIVE = DialogInterface.BUTTON_NEGATIVE;
    public static final int BUTTON_NEUTRAL = DialogInterface.BUTTON_NEUTRAL;

    public void show() { }
    public void dismiss() { }
    public void cancel() { }
    public void setButton(int which, CharSequence text,
                          DialogInterface.OnClickListener l) { }

    public static class Builder {
        public Builder(Context c) { }
        public Builder setTitle(CharSequence t) { return this; }
        public Builder setView(View v) { return this; }
        public Builder setItems(String[] i, DialogInterface.OnClickListener l) { return this; }
        public Builder setPositiveButton(CharSequence t, DialogInterface.OnClickListener l) { return this; }
        public Builder setNeutralButton(CharSequence t, DialogInterface.OnClickListener l) { return this; }
        public Builder setNegativeButton(CharSequence t, DialogInterface.OnClickListener l) { return this; }
        public Builder setCancelable(boolean b) { return this; }
        public AlertDialog create() { return new AlertDialog(); }
        public AlertDialog show() { return new AlertDialog(); }
    }
}
