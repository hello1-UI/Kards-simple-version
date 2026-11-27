package android.content;

/** 编译检查桩（真机签名一致）。 */
public interface SharedPreferences {
    Editor edit();
    String getString(String key, String defValue);
    interface Editor {
        Editor putString(String key, String value);
        void apply();
    }
}
