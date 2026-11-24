const path = require('path');
const express = require('express');
const cors = require('cors');
const mongoose = require('mongoose');
const routes = require('./routes');
const whatsapp = require('./whatsapp');
const { loadCatalogs } = require('./catalog');

const PORT = process.env.PORT || 3000;
const MONGO_URL = process.env.MONGO_URL || 'mongodb://localhost:27017/dukaanbot';
const CATALOG_DIR = process.env.CATALOG_DIR || path.join(__dirname, '..', '..', 'catalog');

async function main() {
  await mongoose.connect(MONGO_URL);
  const loaded = await loadCatalogs(CATALOG_DIR);
  console.log('Catalogs loaded:', JSON.stringify(loaded));

  const app = express();
  app.use(cors());
  app.use(express.json());
  app.use(express.static(path.join(__dirname, '..', 'public')));
  app.use(routes);
  app.use(whatsapp);

  app.listen(PORT, () => console.log(`Backend listening on port ${PORT}`));
}

main().catch((err) => {
  console.error('Failed to start:', err);
  process.exit(1);
});
