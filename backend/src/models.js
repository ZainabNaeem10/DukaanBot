const mongoose = require('mongoose');
const { Schema } = mongoose;

const Store = mongoose.model('Store', new Schema({
  store_id: { type: String, unique: true, required: true },
  name: String,
  city: String,
  delivery_policy: String,
  delivery_charge: Number,
  return_policy: String,
  payment_options: [String],
}));

const productSchema = new Schema({
  store_id: { type: String, required: true, index: true },
  sku: { type: String, required: true },
  name: String,
  category: String,
  fabric: String,
  colors: [String],
  sizes: [String],
  price: Number,
  stock: { type: Map, of: Number }, // units left per size
  description: String,
});
productSchema.index({ store_id: 1, sku: 1 }, { unique: true });
const Product = mongoose.model('Product', productSchema);

const Conversation = mongoose.model('Conversation', new Schema({
  store_id: String,
  conversation_id: { type: String, unique: true, required: true },
  messages: [{
    role: { type: String, enum: ['customer', 'bot'] },
    text: String,
    ts: { type: Date, default: Date.now },
  }],
  language: String,
  escalated: { type: Boolean, default: false },
  escalate_reason: String,
}, { timestamps: true }));

const Order = mongoose.model('Order', new Schema({
  store_id: String,
  conversation_id: String,
  items: [{
    sku: String,
    name: String,
    size: String,
    color: String,
    qty: Number,
    unit_price: Number,
  }],
  customer: { name: String, address: String, phone: String },
  items_total: Number,
  delivery_charge: Number,
  status: { type: String, default: 'new' },
}, { timestamps: true }));

module.exports = { Store, Product, Conversation, Order };
