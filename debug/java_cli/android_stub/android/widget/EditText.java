package android.widget;

import android.content.Context;

/** 编译检查桩（真机签名一致）。 */
public class EditText extends TextView {
    public EditText(Context c) { super(c); }
    public void setHint(CharSequence hint) { }
    public void setSingleLine(boolean b) { }
    public void setInputType(int type) { }
    public CharSequence getText() { return ""; }
}
