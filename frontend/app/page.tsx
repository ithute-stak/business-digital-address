const capabilities = [
  ["Official business identity", "A stable digital address linked to the registered business and its TIN."],
  ["Official communications", "A retained inbox for authorised government and agency communications."],
  ["Verified forwarding", "Businesses can later attach a verified custom email without losing the official copy."],
  ["Ithute security", "Human access is delegated to Ithute Auth instead of sharing mailbox passwords."],
];

export default function HomePage() {
  const authUrl = process.env.NEXT_PUBLIC_AUTH_URL ?? "https://auth.ithute.co.ls";

  return (
    <main>
      <header className="topbar">
        <div className="brand">
          <span className="brandMark">B</span>
          <span>
            <strong>Business Digital Address</strong>
            <small>Official communications platform</small>
          </span>
        </div>
        <a className="signIn" href={`${authUrl.replace(/\/$/, "")}/account/login`}>
          Sign in with Ithute Auth
        </a>
      </header>

      <section className="hero">
        <div className="heroCopy">
          <span className="eyebrow">Built on the Ithute platform</span>
          <h1>One trusted digital address for every registered business.</h1>
          <p>
            Link registration records, TINs and authorised business owners to an official communication address while
            keeping government messages in a durable business inbox.
          </p>
          <div className="heroActions">
            <a href="#foundation" className="primaryAction">Explore the foundation</a>
            <span className="statusPill">Foundation build · not production live</span>
          </div>
        </div>
        <div className="addressCard" aria-label="Example official business address">
          <span className="cardLabel">Official Business Address</span>
          <strong>b000012345@business.ls</strong>
          <div className="addressMeta">
            <span>Registration: 000012345</span>
            <span>TIN: linked privately</span>
          </div>
          <div className="deliveryFlow">
            <span>Official inbox</span>
            <span className="arrow">→</span>
            <span>Verified business email</span>
          </div>
        </div>
      </section>

      <section id="foundation" className="section">
        <div className="sectionHeading">
          <span className="eyebrow">First platform slice</span>
          <h2>The foundation is separated cleanly from Ithute.</h2>
          <p>Business records remain here. Ithute provides identity, mailbox provisioning and shared infrastructure.</p>
        </div>
        <div className="capabilityGrid">
          {capabilities.map(([title, body]) => (
            <article className="capability" key={title}>
              <span className="capabilityDot" />
              <h3>{title}</h3>
              <p>{body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="flowSection">
        <div>
          <span className="eyebrow">Registration flow</span>
          <h2>Register once. Route official communication by TIN.</h2>
        </div>
        <ol className="flowList">
          <li><b>01</b><span>Business registration creates the business record and canonical digital address.</span></li>
          <li><b>02</b><span>Ithute Auth activates and secures the authorised human identity.</span></li>
          <li><b>03</b><span>Ithute Mail provisions the official mailbox after the domain is approved and delegated.</span></li>
          <li><b>04</b><span>Agency communications are retained first, then optional forwarding happens separately.</span></li>
        </ol>
      </section>

      <footer>
        <span>Business Digital Address</span>
        <span>Standalone product · Ithute platform integration</span>
      </footer>
    </main>
  );
}
