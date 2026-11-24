const express = require('express');
const { Store, Product, Conversation, Order } = require('./models');
const { loadCatalogs } = require('./catalog');
const { processMessage } = require('./chat');

const router = express.Router();
const AI_URL = process.env.AI_SERVICE_URL || 'http://localhost:8000';
const CATALOG_DIR = process.env.CATALOG_DIR || './catalog';

router.get('/health', (req, res) => res.json({ status: 'ok' }));

router.post('/api/chat', async (req, res) => {
  try {
    const { store_id, conversation_id, message } = req.body || {};
    if (typeof message !== 'string' || !message.trim()) {
      return res.status(400).json({ error: 'message is required' });
    }
    res.json(await processMessage({ store_id, conversation_id, message }));
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'internal error' });
  }
});

router.get('/api/orders', async (req, res) => {
  const filter = req.query.store_id ? { store_id: req.query.store_id } : {};
  res.json(await Order.find(filter).sort({ createdAt: -1 }).limit(100));
});

router.get('/api/conversations', async (req, res) => {
  const filter = {};
  if (req.query.store_id) filter.store_id = req.query.store_id;
  if (req.query.escalated === 'true') filter.escalated = true;
  res.json(await Conversation.find(filter).sort({ updatedAt: -1 }).limit(100));
});

router.get('/api/stores', async (req, res) => {
  const stores = await Store.find({}, { store_id: 1, name: 1, _id: 0 }).sort({ store_id: 1 });
  res.json(stores);
});

router.get('/api/catalog/:storeId', async (req, res) => {
  const store = await Store.findOne({ store_id: req.params.storeId });
  if (!store) return res.status(404).json({ error: 'store not found' });
  const products = await Product.find({ store_id: req.params.storeId });
  res.json({ store, products });
});

// Re-reads the catalog files, then asks the AI service to rebuild its index.
router.post('/api/catalog/reload', async (req, res) => {
  try {
    const loaded = await loadCatalogs(CATALOG_DIR);
    let reindex = null;
    try {
      const r = await fetch(`${AI_URL}/reindex`, { method: 'POST', signal: AbortSignal.timeout(60000) });
      reindex = await r.json();
    } catch (err) {
      reindex = { error: err.message };
    }
    res.json({ loaded, reindex });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: err.message });
  }
});

module.exports = router;
