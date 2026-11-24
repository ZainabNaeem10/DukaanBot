const crypto = require('crypto');
const { Store, Product, Conversation, Order } = require('./models');

const AI_URL = process.env.AI_SERVICE_URL || 'http://localhost:8000';

// Calls the AI service. The request/response format is defined in docs/contract.md.
async function callAI(payload) {
  const res = await fetch(`${AI_URL}/respond`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(30000),
  });
  if (!res.ok) throw new Error(`AI service returned ${res.status}`);
  const data = await res.json();
  if (typeof data.reply !== 'string') throw new Error('AI response has no reply');
  return data;
}

async function saveOrder(storeId, conversationId, order) {
  const store = await Store.findOne({ store_id: storeId });
  const items = [];
  for (const it of order.items || []) {
    const product = await Product.findOne({ store_id: storeId, sku: it.sku });
    items.push({
      sku: it.sku,
      name: product ? product.name : it.sku,
      size: it.size,
      color: it.color,
      qty: it.qty || 1,
      unit_price: product ? product.price : 0,
    });
  }
  const itemsTotal = items.reduce((sum, i) => sum + i.unit_price * i.qty, 0);
  return Order.create({
    store_id: storeId,
    conversation_id: conversationId,
    items,
    customer: { name: order.name, address: order.address, phone: order.phone },
    items_total: itemsTotal,
    delivery_charge: store ? store.delivery_charge : 0,
  });
}

// One customer message in, one reply out. Used by the web chat and by WhatsApp.
async function processMessage({ store_id = 'store_002', conversation_id, message }) {
  const convId = conversation_id || crypto.randomUUID();
  const conv = (await Conversation.findOne({ conversation_id: convId })) ||
    new Conversation({ store_id, conversation_id: convId, messages: [] });

  const history = conv.messages.slice(-10).map((m) => ({ role: m.role, text: m.text }));
  conv.messages.push({ role: 'customer', text: message });

  let ai;
  try {
    ai = await callAI({ store_id, conversation_id: convId, message, history });
  } catch (err) {
    console.error('AI service error:', err.message);
    ai = {
      reply: 'Sorry, something went wrong on our side. The seller will reply to you soon.',
      language: 'en',
      intent: 'error',
      escalate: true,
      escalate_reason: 'ai_service_error',
      order: null,
      grounded: false,
    };
  }

  conv.messages.push({ role: 'bot', text: ai.reply });
  if (ai.language) conv.language = ai.language;
  if (ai.escalate) {
    conv.escalated = true;
    conv.escalate_reason = ai.escalate_reason || 'unspecified';
  }
  await conv.save();

  let savedOrder = null;
  if (ai.order && Array.isArray(ai.order.items) && ai.order.items.length) {
    savedOrder = await saveOrder(store_id, convId, ai.order);
  }

  return {
    conversation_id: convId,
    reply: ai.reply,
    escalate: !!ai.escalate,
    escalate_reason: ai.escalate_reason || null,
    order: savedOrder,
  };
}

module.exports = { processMessage };
