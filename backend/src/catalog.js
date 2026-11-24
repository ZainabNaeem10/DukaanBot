const fs = require('fs');
const path = require('path');
const { Store, Product } = require('./models');

// Reads every *.json file in dir ({ store: {...}, products: [...] }) and upserts it.
async function loadCatalogs(dir) {
  const files = fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => f.endsWith('.json')) : [];
  const summary = [];
  for (const file of files) {
    const data = JSON.parse(fs.readFileSync(path.join(dir, file), 'utf8'));
    const { store, products } = data;
    await Store.updateOne({ store_id: store.store_id }, { $set: store }, { upsert: true });
    const ops = products.map((p) => ({
      updateOne: {
        filter: { store_id: store.store_id, sku: p.sku },
        update: { $set: { ...p, store_id: store.store_id } },
        upsert: true,
      },
    }));
    if (ops.length) await Product.bulkWrite(ops);
    summary.push({ file, store_id: store.store_id, products: products.length });
  }
  return summary;
}

module.exports = { loadCatalogs };
