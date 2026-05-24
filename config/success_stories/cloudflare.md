# Cloudflare — aggressive free tier as a market-creation weapon

## Founding insight
Matthew Prince, Lee Holloway, and Michelle Zatlyn saw that internet security was sold to *enterprises*, but small sites were getting DDoS'd into nonexistence without any affordable protection. The contrarian bet: give it away free, build a massive long-tail user base, then upsell enterprise security/edge compute on top of a platform nobody else had the data or footprint to match. Generosity at the bottom funds dominance at the top.

## Initial wedge
Small site owners on shared hosting, bloggers, indie communities — sites that couldn't pay $5K/month for Akamai but were getting attacked. Sign up, change two DNS records, attacks stop. Zero friction, zero cost.

## Timing call
2010-2011. The DDoS landscape was professionalizing (botnets became cheap), small sites couldn't survive without protection, and CDN economics had cratered (commodity bandwidth). Three years earlier the demand wasn't there; later, AWS would start eating the same infra space with its own CDN.

## Distribution mechanism
Hosting providers (HostGator, WP Engine, etc.) bundled Cloudflare into their offerings — instant millions of sites. Hacker News + tech blog endorsements compounded it. By the time Cloudflare started seriously selling enterprise, they had unmatched real-time threat intelligence from billions of requests/day across the long tail.

## 10× moment
*Free as a strategic weapon*. Akamai's enterprise plans started at five figures; Cloudflare's was zero. The 10× was on the *price/value-curve floor* — they redefined what was available at the bottom, then compounded upward. The free tier wasn't a freemium funnel — it was the moat.

## Default-status moat
The data + footprint feedback loop. Every request through Cloudflare improved its threat intel and edge cache; that improvement made enterprise customers want it more, which funded more edge presence, which made the free product better. Decade-compounding flywheel that turned a free CDN into a $30B+ infra business. Hard to replicate because catching up requires running a free service at Cloudflare's scale — and nobody will fund that for an incumbent.
