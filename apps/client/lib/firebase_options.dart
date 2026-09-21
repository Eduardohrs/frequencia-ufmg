// Generated from the Firebase project configuration.
// coverage:ignore-file

import 'package:firebase_core/firebase_core.dart' show FirebaseOptions;
import 'package:flutter/foundation.dart'
    show TargetPlatform, defaultTargetPlatform, kIsWeb;

abstract final class DefaultFirebaseOptions {
  static FirebaseOptions get currentPlatform {
    if (kIsWeb) {
      return web;
    }

    return switch (defaultTargetPlatform) {
      TargetPlatform.android => android,
      _ => throw UnsupportedError(
        'Firebase ainda não foi configurado para esta plataforma.',
      ),
    };
  }

  static const FirebaseOptions web = FirebaseOptions(
    apiKey: 'AIzaSyANIBLey3zozghmbZx94CBe3pCgWR6SbDg',
    appId: '1:932945721608:web:65cba3319f9ecc78b8d4bd',
    messagingSenderId: '932945721608',
    projectId: 'frequencia-ufmg-eduardo',
    authDomain: 'frequencia-ufmg-eduardo.firebaseapp.com',
    storageBucket: 'frequencia-ufmg-eduardo.firebasestorage.app',
    measurementId: 'G-S5TTZ479Z4',
  );

  static const FirebaseOptions android = FirebaseOptions(
    apiKey: 'AIzaSyDfVSpbDRoyPZP0aZB-6eBsEP_YUl0akn4',
    appId: '1:932945721608:android:2002f4db3d2942cab8d4bd',
    messagingSenderId: '932945721608',
    projectId: 'frequencia-ufmg-eduardo',
    storageBucket: 'frequencia-ufmg-eduardo.firebasestorage.app',
  );
}
