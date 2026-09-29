# Firefox signing releases

Sleeper distributes Firefox releases as an AMO-signed, **unlisted** XPI. An unlisted signing submission lets the project host the signed XPI in its GitHub Release while Firefox enforces Mozilla's signature. It does not create a public AMO listing. Mozilla requires signed add-ons on Firefox Release and Beta.

The release workflow runs `scripts/sign-firefox.sh` after the normal package build. It submits `extension/` with `web-ext sign --channel unlisted` and attaches only `build/sleeper-firefox.xpi` to the release. The locally built `build/sleeper.xpi` remains a development artifact and is deliberately not offered as the persistent Firefox package.

Before the first signed release, a maintainer must create AMO Developer Hub API credentials and add their two values as repository Actions secrets:

- `AMO_JWT_ISSUER`: the AMO API key (JWT issuer).
- `AMO_JWT_SECRET`: the AMO API secret.

The workflow fails before network submission when either secret is absent. It does not generate credentials or bypass Firefox signature enforcement. This checkout has no configured AMO credential signal, so publishing a persistent Firefox XPI remains externally blocked until the maintainer completes that setup.

Sources: Mozilla's [Signing and distribution overview](https://extensionworkshop.com/documentation/publish/signing-and-distribution-overview/), [Getting started with web-ext](https://extensionworkshop.com/documentation/develop/getting-started-with-web-ext/), and [web-ext command reference](https://extensionworkshop.com/documentation/develop/web-ext-command-reference/).
