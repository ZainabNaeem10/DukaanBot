const express = require('express');
const { processMessage } = require('./chat');

const router = express.Router();

const VERIFY_TOKEN = process.env.WHATSAPP_VERIFY_TOKEN;
const TOKEN = process.env.WHATSAPP_TOKEN;
const PHONE_NUMBER_ID = process.env.WHATSAPP_PHONE_NUMBER_ID;
const API_VERSION = process.env.WHATSAPP_API_VERSION || 'v21.0'; // check Meta docs for the current version
const STORE_ID = process.env.WHATSAPP_STORE_ID || 'store_002';

const seen = new Set(); // message ids already handled (WhatsApp can deliver a message twice)

// Step 1: Meta calls this once to check that the webhook URL is yours.
router.get('/webhook', (req, res) => {
  const mode = req.query['hub.mode'];
  const token = req.query['hub.verify_token'];
  const challenge = req.query['hub.challenge'];
  if (mode === 'subscribe' && VERIFY_TOKEN && token === VERIFY_TOKEN) {
    return res.status(200).send(challenge);
  }
  res.sendStatus(403);
});

async function sendText(to, body) {
  if (!TOKEN || !PHONE_NUMBER_ID) {
    console.warn('WhatsApp not configured (WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID); reply not sent:', body);
    return;
  }
  const res = await fetch(`https://graph.facebook.com/${API_VERSION}/${PHONE_NUMBER_ID}/messages`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ messaging_product: 'whatsapp', to, type: 'text', text: { body } }),
    signal: AbortSignal.timeout(15000),
  });
  if (!res.ok) console.error('WhatsApp send failed:', res.status, await res.text());
}

async function handleIncoming(body) {
  for (const entry of body.entry || []) {
    for (const change of entry.changes || []) {
      const value = change.value || {};
      for (const msg of value.messages || []) {
        if (seen.has(msg.id)) continue;
        seen.add(msg.id);
        if (seen.size > 5000) seen.clear();

        if (msg.type !== 'text') {
          await sendText(msg.from, 'Sorry, I can only read text messages for now.');
          continue;
        }
        // One conversation per customer phone number.
        const result = await processMessage({
          store_id: STORE_ID,
          conversation_id: `wa-${msg.from}`,
          message: msg.text.body,
        });
        await sendText(msg.from, result.reply);
      }
    }
  }
}

// Step 2: Meta posts every incoming message here. Answer 200 straight away, then do the slow work.
router.post('/webhook', (req, res) => {
  res.sendStatus(200);
  handleIncoming(req.body || {}).catch((err) => console.error('WhatsApp handler error:', err));
});

module.exports = router;
