# Vercel — DX-as-moat by owning the framework that owned the deployments

## Founding insight
Guillermo Rauch saw that frontend deployment was still painful in 2016 (Heroku existed for backend, but static sites + modern frontend frameworks had no equivalent). The contrarian bet: don't compete on hosting features — *create the framework that defines the workflow*, then attach the deployment platform to it. Tie open-source distribution to commercial cloud the way Red Hat did with Linux but for the modern web.

## Initial wedge
Next.js developers — the React community that wanted SSR + static generation without configuring Webpack, Babel, and CDN deployment themselves. Next.js shipped first as open source; Vercel (then Zeit) became the default "git push and it's live" target. Indie hackers + small product teams.

## Timing call
2016-2018. React had won the framework war, but production deployment was still hand-rolled. JAMstack was emerging; serverless was getting credible. Two years earlier React wasn't dominant enough; two years later AWS Amplify and Netlify would be everywhere.

## Distribution mechanism
Next.js as Trojan horse. Every Next.js tutorial defaulted to deploying on Vercel. The framework's GitHub stars (now 130K+) translated directly to platform adoption. Strong dev-conference + Twitter presence; Rauch personally wrote about the philosophy. Free tier generous enough to onboard students, paid tier priced for serious teams.

## 10× moment
*Zero-config deploys for the most-used React framework on the planet*. Git push → live URL in 30 seconds, with previews per pull request. The 10× was the integration depth between framework and platform — Netlify and AWS could match features but not the framework lock.

## Default-status moat
For Next.js apps, Vercel is *the* hosting target. Microsoft and Cloudflare have tried alternatives, but the framework-defines-the-deployment loop means even if a competitor matches the platform features, Next.js itself routes you back to Vercel via defaults, docs, and developer mindshare. The OSS framework strategy created a $3B+ company by making the framework the moat.
