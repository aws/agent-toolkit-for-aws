---
source_url: https://aws.amazon.com/startups/learn/why-early-stage-startups-need-to-use-multi-factor-authentication
title: "Why early stage startups need to use multi-factor authentication"
---

## Why early stage startups need to use multi-factor authentication

Every startup is unique – there's no universal to-do list that fits every company. But no matter the nature of your business, security is always of primary importance and should be one of the very first things you address. After all, for most startups, your most valuable asset is your data — your ideas, workloads, and applications — and you need to protect it. We often tell startups to make lots of mistakes, just not fatal ones. A security breach can be a fatal one.

While there is no 100% guaranteed way to protect your data, the one thing you absolutely need to do is use multi-factor authentication (MFA) to protect your accounts. MFA is an authentication method that requires the user to provide two or more verification factors to gain access to a resource. Startups sometimes move so quickly that they don't take the time to set up MFA, but we highly recommend configuring MFA to protect AWS resources if you haven't done so already.

## The Risk of NOT setting up MFA

- **Vulnerability**: A single password is not enough, regardless of how complex it is. Hackers have ways to crack passwords.
- **Non-compliance**: MFA may be a required component of compliance standards.
- **Your business reputation**: You don't want to have to answer questions from your customers about why you don't have sufficient security protocols in place to protect both your business and their personal data.

## MFA on AWS

MFA provides an extra layer of security, because it requires users to provide unique authentication from an AWS-supported MFA mechanism in addition to their regular sign-in credentials (username and password) when they access AWS websites or services, and it forces users not to share passwords. Customers can enable MFA for their AWS account root user and IAM users. When you enable MFA for the root user, it affects only the root user credentials. IAM users in the account are distinct identities with their own credentials, and each identity has its own MFA configuration.

## Types of MFA

AWS supports three types of MFA devices: virtual MFA devices, U2F security keys, and hardware MFA devices. Virtual MFA devices are software-based apps, usually running on a mobile device, that generate secure, one-time authentication codes that are used as part of the sign-on process. U2F security keys and hardware MFA devices are physical devices that are required to gain access to the accounts to which they are attached. These physical devices are considered the most secure options for MFA, and they can be stored in a safe or lockbox for additional security. Though virtual MFA devices may be more convenient since they can run on mobile phones and are good option in most instances, they are considered less secure than physical devices. At the very least, we recommend that you use a virtual MFA device while waiting for hardware purchase approval or while you wait for your hardware to arrive.

You can also consult the AWS Identity and Access Management [user guide](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_mfa.html) for more information on using MFA.

Since MFA is so important, AWS will also provide an MFA device at no cost to qualified account holders. You will be able to use MFA devices to safely access multiple AWS accounts, as well as other token-enabled applications. You can read more about our security initiatives [on the Amazon security initiatives page](https://aws.amazon.com/security/amazon-security-initiatives/).

## Try it yourself

If you have already configured multi-factor authentication across your startup, congratulations, you're ahead of the curve! However, if your use of MFA has gaps, now is the time to set it up.

By following these steps, you can set up MFA in just a few minutes.

First, sign in to the AWS Management Console and open the **IAM** console. Choose a user, then choose the **Security credentials** tab. Click the **Manage** button next to the **Assigned MFA device**.

In the Manage MFA Device wizard, choose the type of multi-factor device. In this example we will show you how to setup a virtual MFA device. You can install a mobile app that is compliant with RFC 6238, a standards-based TOTP (time-based one-time password) algorithm, such as Authy, Duo Mobile, and LastPass Authenticator. These apps generate a six-digit authentication code.

Click **Continue**, and on next page IAM generates and displays configuration information for the virtual MFA device, including a QR code graphic. The graphic is a representation of the "secret configuration key" that is available for manual entry on devices that do not support QR codes.

Determine whether the MFA app supports QR codes, and then do one of the following:

- From the wizard, choose **Show QR code**, and then use the app to scan the QR code. For example, you might choose the camera icon or choose an option similar to scan code, and then use the device's camera to scan the code.
- Choose **Show secret key**, and then type the secret key into your MFA app.

When you are finished, the virtual MFA device starts generating one-time passwords. In the **Manage MFA** Device wizard, in the **MFA code 1** box, type the one-time password that currently appears in the virtual MFA device. You then need to wait up to 30 seconds for the device to generate a new one-time password. Type the second one-time password into the **MFA code 2** box. Click **Assign MFA**.

You're all set! You can see the assigned MFA device information under user Security credentials tab. If you're using a U2F security key or hardware MFA device, the setup will be very similar. You get the code from the security key or the hardware device rather than from a mobile app. Next time, when you log in, you'll use your regular credentials as well as an MFA password. Everything will continue to work just as before. It's a simple and important step to safeguard your account.

Further, it is equally critical to implement these measures in your other platforms as well as in your personal life — after all, if hackers are able to gain access to your own digital resources, it could provide a gateway to exploiting those of your company. Startups are especially vulnerable here, since in the early days, personal and company assets often overlap and bleed into each other in both understandable and unexpected ways.

For startups, focusing on security can often be seen as a blocker. But setting up MFA is an essential step in your company's growth — one that will safeguard your most valuable assets and set you up for continued success.

---

## Authors

### Xuan Gao

Xuan Gao is a Solutions Architect at AWS on the Startups team, where she helps startups grow their business and achieve their goals by using AWS efficiently. She is passionate about cloud technologies. She loves traveling and cooking in her free time.

### AWS Editorial Team

The AWS Startups Content Marketing Team collaborates with startups of all sizes and across all sectors to deliver exceptional content that educates, entertains, and inspires.
