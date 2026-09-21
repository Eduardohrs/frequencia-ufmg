import 'package:flutter/material.dart';

void main() {
  runApp(const FrequenciaUFMGApp());
}

class FrequenciaUFMGApp extends StatelessWidget {
  const FrequenciaUFMGApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Frequência UFMG',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF006633)),
        useMaterial3: true,
      ),
      home: const Scaffold(
        body: Center(
          child: Text('Frequência UFMG'),
        ),
      ),
    );
  }
}
