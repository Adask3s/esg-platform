export const config = {
  matcher: '/((?!_next|favicon|robots\\.txt|assets).*)',
};

export default function middleware(req) {
  // Lokalne dev (npm run dev) NIE ma DEMO_PASS -> middleware przepuszcza.
  // Gate aktywny tylko gdy DEMO_PASS ustawione w Vercel env vars.
  if (!process.env.DEMO_PASS) {
    return;
  }

  const auth = req.headers.get('authorization');
  const expected =
    'Basic ' +
    btoa(`${process.env.DEMO_USER || 'demo'}:${process.env.DEMO_PASS}`);

  if (auth !== expected) {
    return new Response('Authentication required', {
      status: 401,
      headers: {
        'WWW-Authenticate': 'Basic realm="ESG Demo"',
        'Content-Type': 'text/plain',
      },
    });
  }
}
