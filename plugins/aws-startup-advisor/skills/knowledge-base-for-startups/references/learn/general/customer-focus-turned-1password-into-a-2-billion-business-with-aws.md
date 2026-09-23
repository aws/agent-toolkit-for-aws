---
source_url: https://aws.amazon.com/startups/learn/customer-focus-turned-1password-into-a-2-billion-business-with-aws
title: "Customer focus turned 1Password into a $2 billion business with AWS"
---

## Customer focus turned 1Password into a $2 billion business with AWS

> **Source:** [AWS Startups](https://startups.aws/startups/learn/customer-focus-turned-1password-into-a-2-billion-business-with-aws)

**Author:** AWS Editorial Team

---

Back in 2005, Roustem Karimov and Dave Teare were web consultants helping other folks build e-commerce sites when they started a side project to help keep track of all the different passwords needed for work. At the time, Roustem recalls thinking, "Hey, we'll spend a few weeks on this, and then we'll just go back to doing our real job web consulting stuff."

But it became clear shortly after they finished building the product and put a purchase form up that Roustem and Dave wouldn't be returning to their day jobs any time soon. "The very first hour we put it online, someone bought it," Roustem says. Revenues from the first year totaled roughly $80,000, causing the pair to drop everything and devote their full attention to building [1Password](https://1password.com/). That turned out to be the right instinct: this past summer, the company raised a Series B round that doubled its valuation, making 1Password worth $2 billion today.

![Founder Roustem Karimov](https://d22k7geae6sy8h.cloudfront.net/files/64affdcd2dc1e10008bb861e/8lk171857-Roustem-Karimov-Headshot.jpg)

Roustem is quick to note, though, that it took a decade and a half to build the company to what it is today—and those early years were lean ones. "We lived on ramen noodles." It was just Roustem and Dave, a two-person team, doing everything themselves: development, marketing, customer support, making sure the web store stayed online, "because if this thing goes down, you don't have any revenue coming in. You're basically out of business."

He still remembers the panicked texts coming in at 2 a.m. "The service is down, wake up!" But that all began to change when 1Password started relying on AWS to manage their service. "It's off my shoulders. Everything is taken care of for me," Roustem remembers marveling. "The backups are happening, upgrades are happening—I don't have to worry about that."

Today, 1Password still has objects stored on [Amazon S3](https://aws.amazon.com/s3/) that date all the way back to 2007. "It may be the biggest compliment that you don't really have to think about it too much," Roustem says of S3. "You put things there, they will be there. You don't have to perform maintenance or worry about availability."

For a business that is built almost entirely on customer trust—after all, no one is going to use a password storage service they can't rely on to retrieve their stored passwords—finding a dependable partner early was key to 1Password's success. "We were really, really cautious," Roustem explains. "People have put a lot of trust in our service and our app. If you screwed up, it would be really hard to recover." Once the pair knew they could trust AWS, they took advantage of as many of AWS's offerings as they could, including [re:Invent](https://reinvent.awsevents.com/), AWS's annual learning conference, which Roustem attended for the first time in 2014.

He still beams as he recalls the panel discussions on the topic of, say, migrating to a Virtual Private Cloud. "We used a lot of the stuff that we learned at re:Invent to design the service, to make it as secure as possible, as resilient as possible, to be able to make sure that there is no single point of failure, and that if something goes down, things just heal themselves," Roustem says.

Today, Roustem has peace of mind knowing not only have they built a secure, resilient service, but it is also robust enough to stay that way as it grows. "We've been leveraging [Amazon Aurora](https://aws.amazon.com/rds/aurora/) for a while now and have been really happy with how the databases hold up. We love that as we scale, the service is able to upgrade instance sizes to support more customers." Even with the millions of existing users who login to 1Password every day, Roustem is confident "tomorrow we could have 10 times more customers, and we still have room to grow. And that feels really nice."

![The 1Password Founders](https://d22k7geae6sy8h.cloudfront.net/files/64affe962dc1e10008bb861f/8lk175j34-1Password-Founders.jpg)

The company itself continues to grow in the meantime. What started as a two-person team subsisting on ramen noodles numbers almost 500 members today. "Looking back, we didn't have an HR department, we didn't have a finance department, and we didn't have a sales team. There are so many things we didn't have," Roustem recalls. "We had to build them from scratch."

It's exciting, but for someone who was used to doing it all himself, Roustem is now faced with a new challenge: figuring out how to best manage the growing team. "We have so many smart and talented people, and I'm just trying to stay out of the way these days," he laughs. "That's my job."

---

## About the Author

### AWS Editorial Team

The AWS Startups Content Marketing Team collaborates with startups of all sizes and across all sectors to deliver exceptional content that educates, entertains, and inspires.
