# Keep Jackson / mapper models used by youtubedl-android
-keep class com.yausername.youtubedl_android.mapper.** { *; }
-keep class com.fasterxml.jackson.** { *; }
-dontwarn com.fasterxml.jackson.**
-keepattributes *Annotation*,Signature,InnerClasses,EnclosingMethod
