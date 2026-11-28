-keepattributes Signature,InnerClasses,EnclosingMethod

-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}

-keep class top.mayano.sweepy.core.** { *; }
-keep class org.msgpack.core.buffer.** { *; }

-dontwarn sun.misc.Unsafe
-dontwarn sun.nio.ch.DirectBuffer
-dontwarn java.lang.management.**
-dontwarn javax.annotation.**
-dontwarn org.codehaus.mojo.animal_sniffer.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**
-dontwarn okhttp3.internal.platform.**
-dontwarn okio.**
