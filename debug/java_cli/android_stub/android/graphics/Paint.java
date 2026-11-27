package android.graphics;

public class Paint {
    public static final int ANTI_ALIAS_FLAG = 1;
    public enum Style { FILL, STROKE }
    public Paint() { }
    public Paint(int flags) { }
    public void setColor(int c) { }
    public void setStyle(Style s) { }
    public void setStrokeWidth(float w) { }
    public void setTextSize(float s) { }
    public float measureText(String s) { return 0; }
}
