package android.content;

/** 编译检查桩（真机签名一致）。 */
public interface DialogInterface {
    int BUTTON_POSITIVE = -1;
    int BUTTON_NEGATIVE = -2;
    int BUTTON_NEUTRAL = -3;

    void dismiss();
    void cancel();

    interface OnClickListener {
        void onClick(DialogInterface dlg, int which);
    }
}
