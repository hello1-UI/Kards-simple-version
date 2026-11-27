package android.app;
import android.content.Context;
import android.content.DialogInterface;
public class AlertDialog { public static class Builder { public Builder(Context c){} public Builder setTitle(CharSequence t){return this;} public Builder setItems(String[] i, DialogInterface.OnClickListener l){return this;} public Builder setCancelable(boolean b){return this;} public AlertDialog show(){return null;} } }
