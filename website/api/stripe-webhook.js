// Vercel Serverless Webhook Handler for Stripe Events
// Endpoint: https://www.gopoint.store/api/stripe-webhook

const Stripe = require('stripe');

// Read raw body helper for Stripe signature verification
export const config = {
  api: {
    bodyParser: false,
  },
};

async function getRawBody(readable) {
  const chunks = [];
  for await (const chunk of readable) {
    chunks.push(typeof chunk === 'string' ? Buffer.from(chunk) : chunk);
  }
  return Buffer.concat(chunks);
}

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ error: 'Method Not Allowed' });
  }

  const stripeSecretKey = process.env.STRIPE_SECRET_KEY;
  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET;

  if (!stripeSecretKey) {
    console.error('Missing STRIPE_SECRET_KEY in environment variables');
    return res.status(500).json({ error: 'Stripe API key not configured' });
  }

  const stripe = new Stripe(stripeSecretKey, {
    apiVersion: '2023-10-16',
  });

  const sig = req.headers['stripe-signature'];
  let event;

  try {
    const rawBody = await getRawBody(req);
    if (webhookSecret) {
      event = stripe.webhooks.constructEvent(rawBody, sig, webhookSecret);
    } else {
      // In development mode without endpoint secret configured
      event = JSON.parse(rawBody.toString('utf8'));
    }
  } catch (err) {
    console.error(`Webhook signature verification failed: ${err.message}`);
    return res.status(400).send(`Webhook Error: ${err.message}`);
  }

  // Handle successful checkout payment
  if (event.type === 'checkout.session.completed') {
    const session = event.data.object;
    const customerEmail = session.customer_details ? session.customer_details.email : session.customer_email;
    
    console.log(`✅ [Stripe Webhook] Successful payment for GoPoint Pro!`);
    console.log(`   Customer Email: ${customerEmail}`);
    console.log(`   Session ID: ${session.id}`);
    console.log(`   Amount Total: $${(session.amount_total / 100).toFixed(2)} ${session.currency.toUpperCase()}`);

    // Optional: Send automated receipt email or save transaction record here
  }

  res.status(200).json({ received: true, eventType: event.type });
}
