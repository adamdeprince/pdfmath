/*
 * Speak a batch of MathML with MathJax's speech-rule-engine.
 *
 * Reads a JSON request from the file named by argv[2] and writes the answer to argv[3]:
 *
 *   { "domain": "clearspeak", "style": "default", "locale": "en",
 *     "markup": "none", "items": ["<math>...</math>", ...] }
 *   -> { "speech": ["x plus y", ...] }
 *
 * The engine is set up once for the whole batch: starting node and loading the rule
 * tables costs far more than any single expression.
 */
const sre = require('speech-rule-engine');
const fs = require('fs');

(async () => {
  try {
    const req = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
    await sre.setupEngine({
      domain: req.domain || 'clearspeak',
      style: req.style || 'default',
      locale: req.locale || 'en',
      markup: req.markup || 'none',
      modality: 'speech',
    });
    const speech = [];
    for (const item of req.items) {
      speech.push(await sre.toSpeech(item));
    }
    fs.writeFileSync(process.argv[3], JSON.stringify({speech}));
  } catch (err) {
    fs.writeFileSync(process.argv[3], JSON.stringify({error: String(err)}));
    process.exit(1);
  }
})();
