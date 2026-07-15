// Short audio alert - played ONLY when an actual trade is placed (manual
// buy/sell from the Dashboard/Trading page, or an auto-trader entry/exit).
// Deliberately NOT played for scanner candidates appearing/disappearing -
// that fired far too often to be a useful "something happened" signal.
export function playTradeSound() {
  if (!window.AudioContext && !window.webkitAudioContext) return;
  const audioContext = new (window.AudioContext || window.webkitAudioContext)();
  const oscillator = audioContext.createOscillator();
  const gainNode = audioContext.createGain();
  oscillator.connect(gainNode);
  gainNode.connect(audioContext.destination);
  oscillator.frequency.value = 800;
  oscillator.type = "sine";
  gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
  oscillator.start();
  oscillator.stop(audioContext.currentTime + 0.2);
}
