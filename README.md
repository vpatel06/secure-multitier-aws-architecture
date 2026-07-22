# Secure Multi-Tier AWS Cloud Architecture

This is a project I built to actually get hands-on with the kind of AWS architecture that shows up constantly in Solutions Architect interviews and on the SAA exam — a proper multi-tier network with real network isolation, not just spinning up a single EC2 instance and calling it a day.

I built everything manually through the AWS console instead of using Terraform (which I'd already used on a couple other projects) specifically so I'd actually understand every piece — every route table, every security group rule — instead of running `terraform apply` on a module I copied from somewhere.

## What it actually is

A Flask + PostgreSQL API deployed across a real three-tier network:

```
                         Internet
                            |
                     [Internet Gateway]
                            |
                    ┌───────────────┐
                    │ Public Subnet │   (just routing, nothing lives here)
                    └───────────────┘
                            |
                    [NAT Gateway]
                            |
        ┌───────────────────┴───────────────────┐
        │                                         │
┌───────────────┐                        ┌───────────────┐
│ App Subnet A   │  us-east-1a            │ App Subnet B   │  us-east-1b
│ EC2 (in ASG)   │                        │ EC2 (in ASG)   │
└───────────────┘                        └───────────────┘
        │                                         │
        └───────────────────┬─────────────────────┘
                             │
                    ┌────────────────┐
                    │ DB Subnet      │   (isolated, no internet route)
                    │ RDS Postgres   │
                    └────────────────┘
```

- **Public subnet** — literally nothing runs here except the NAT Gateway. It's just the traffic cop for outbound internet access.
- **App subnets (2 AZs)** — EC2 instances running the Flask API, sitting in an Auto Scaling Group so the compute tier survives an instance (or even a whole AZ) going down.
- **DB subnet** — RDS Postgres, completely isolated. No route to the internet at all, and it only accepts traffic from the app tier's security group.
- **VPC Interface Endpoints** — this is how the app instances talk to AWS Systems Manager without ever touching the public internet.

## The decisions and why I made them

**No SSH, anywhere.** Every instance is managed through Systems Manager Session Manager instead. That means no key pairs to lose track of, no port 22 open to the world, and every session is logged through IAM instead of "whoever has the .pem file."

**Security groups are tiered, not flat.** The DB security group only accepts Postgres traffic from the app tier's security group — not from a CIDR range, not from "anywhere," specifically from the other security group. Same logic on the app tier: nothing gets in except through the intended path.

**Auto Scaling Group spans two AZs.** This is the actual reason the compute tier can lose an entire Availability Zone and keep running.

**RDS is single-AZ, not Multi-AZ.** This one I want to be upfront about — I did NOT do this because I ran out of budget or forgot. This app has basically zero real traffic (it was a fake API for testing, not something with real users), so Multi-AZ RDS would be solving a problem that doesn't exist for this workload. I kept the compute tier multi-AZ specifically to practice that pattern, but for the database I made the call that matches what I'd actually recommend if someone asked me "does this need Multi-AZ" — no, not at this scale. If this were a real production app with real traffic, Multi-AZ RDS plus an Application Load Balancer in front of the ASG would be the first two things I'd add.

Being honest about that tradeoff is kind of the point of the project — a lot of student projects just throw every AWS service at something to look impressive, and I'd rather show that I know when a pattern is actually load-bearing versus when I'm using it to practice.

## How I actually proved the isolation works

I didn't just assume the network was locked down because the security group rules looked right on screen — I tested it:

- Tried hitting the app tier's private IP directly from my laptop → connection timed out, exactly what should happen since there's no route in
- Tried hitting the RDS endpoint directly from outside the VPC → refused
- SSM'd into an app instance and hit the API locally → worked fine, and the API successfully read/wrote to the database

That last point matters — it's not enough to prove things are blocked, you also have to prove the thing that's *supposed* to work still works.

## Stack

AWS (VPC, EC2, Auto Scaling, RDS/Postgres, IAM, Systems Manager, NAT Gateway, VPC Endpoints, Security Groups), Python, Flask, SQLAlchemy

## Screenshots

(Adding these in — captured during the actual build/teardown session)

- [ ] VPC map showing the subnet layout
- [ ] Security group rules for both the app and db tiers
- [ ] IAM role showing it's scoped to SSM only, nothing else
- [ ] RDS config screen (subnet group, public access set to No)
- [ ] Auto Scaling Group settings across the two AZs
- [ ] SSM session showing a working `curl localhost:5000/health` hitting the database successfully
- [ ] The failed connection attempt from outside the VPC (this is honestly the most important screenshot — it's the actual proof)

## Teardown

Everything here was built and torn down in the same sitting to avoid leaving anything running and racking up cost — NAT Gateway and Elastic IP first (most expensive), then the ASG, RDS, VPC endpoints, security groups, route tables, IGW, subnets, and finally the VPC itself. Double-checked with the AWS CLI afterward that nothing was left behind.
