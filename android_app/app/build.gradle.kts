import org.jetbrains.kotlin.gradle.tasks.KotlinCompile

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    kotlin("plugin.serialization") version "1.9.20"
}

val resolvedVersionCode = (findProperty("APP_VERSION_CODE") as String?)
    ?.toIntOrNull()
    ?: 1
val resolvedVersionName = (findProperty("APP_VERSION_NAME") as String?)
    ?.takeIf { it.isNotBlank() }
    ?: "1.0"

/** 默认后端 API 根地址（仅首次安装且无本地保存时使用；可在应用「设置」中修改） */
val defaultApiBaseUrl = (
    (findProperty("DEFAULT_API_BASE_URL") as String?)
        ?.takeIf { it.isNotBlank() }
        ?: System.getenv("QUANT_DEFAULT_API_BASE_URL")
        ?.takeIf { it.isNotBlank() }
        ?: "http://101.133.149.141/"
).let { if (it.endsWith("/")) it else "$it/" }

android {
    namespace = "com.quant.system"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.quant.system"
        minSdk = 26
        targetSdk = 34
        versionCode = resolvedVersionCode
        versionName = resolvedVersionName

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables {
            useSupportLibrary = true
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".uifix"
            versionNameSuffix = "-uifix"
            buildConfigField("String", "API_BASE_URL", "\"$defaultApiBaseUrl\"")
        }
        release {
            isMinifyEnabled = false
            buildConfigField("String", "API_BASE_URL", "\"$defaultApiBaseUrl\"")
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.4"
    }
    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.core:core-splashscreen:1.0.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.7.0")
    implementation("androidx.activity:activity-compose:1.8.2")
    implementation(platform("androidx.compose:compose-bom:2024.02.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material:material")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.navigation:navigation-compose:2.7.6")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.7.0")
    
    implementation("com.squareup.retrofit2:retrofit:2.9.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.6.0")
    implementation("com.jakewharton.retrofit:retrofit2-kotlinx-serialization-converter:1.0.0")
    
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")
    implementation("androidx.work:work-runtime-ktx:2.9.0")
    implementation("androidx.fragment:fragment-ktx:1.6.2")
    
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.1.5")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.1")
    androidTestImplementation(platform("androidx.compose:compose-bom:2024.02.00"))
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}

tasks.withType<KotlinCompile>().configureEach {
    exclude("**/com/quant/system/core/test/**")
    exclude("**/com/quant/system/ui/screen/OptimizationTestActivity.kt")
    exclude("**/com/quant/system/ui/screen/OptimizationReportActivity.kt")
}
