# Elderly Home Care Services

A responsive, multi-page static website for Elderly Home Care Services.

## Files

- `index.html` — home page
- `about.html` — about page
- `services.html` — services page
- `contact.html` — contact page
- `assets/style.css` — complete styling
- `assets/script.js` — mobile menu, year, and contact mailto form

## Before publishing

Update the following placeholders in `contact.html`:

- `YOUR PHONE NUMBER`
- `YOUR SERVICE AREA`
- `YOUR BUSINESS HOURS`

Also review all service descriptions so they accurately reflect the actual services, staff qualifications, licensing, and coverage area.

## Free hosting

Recommended: GitHub Pages.

1. Create a public GitHub repository, e.g. `elderly-home-care-services`.
2. Upload all website files while keeping the folder structure.
3. Open repository Settings → Pages.
4. Choose GitHub Actions or the branch publishing option.
5. Publish the site.
6. Add `elderlyhomecareservices.com` under the Pages Custom domain setting.
7. In GoDaddy DNS, configure the GitHub Pages records shown in GitHub's current documentation.
8. Add the `www` CNAME to your GitHub Pages address.
9. Wait for DNS propagation and enable HTTPS in GitHub Pages.

The site is static, so it does not require a paid server.

## Contact form

The included form uses `mailto:` and opens the visitor's email application. It does not store form submissions on a server. For a true web form, connect a form backend/service after deployment.
