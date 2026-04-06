## Table of Contents

- [Info](#Info)
- [Changelog](#changelog)

## Info

This is only a fork made with fixes that I've applied myself since every new change was breaking the bot.

Go get the original, which is not only updated but probably will have all these fixes sometime soon: https://github.com/SweepTosher/umamusume-sweepy

This was made to fix the following issues that were encountered in MANT:

- Events getting stuck only sometimes and with no specific event being the issue. This made the event handler loop like crazy, so now the bot checks the event before trying to loop the logic and triggering the decision making click. Fuck, just had a run where it got stuck again, but it seems to be due to the fact that: It was a G1 race with a Rival, but also the third consecutive race in the schedule, with no good training available without a high failure rate and no recreation, so it kinda gets super dumb and goes into the trainins and back to the main menu, rinse and repeat. I'll figure it out tho

- Bot sometimes getting stuck on the races menu, trying to find a scheduled race but not finding it. Now the bot will lower the threshold for detection everytime it reaches the bottom of the race list, until it finds the race. Don't know what happens if it fails too much tho, it seems to be fine finding it after the second try so it may choose the wrong race or get stuck idk

- Bot getting stuck when trying to use cleats before a race. This one actually was giving me a full blown error that re-started the bot, also in an infinite loop.

- NOT BUYING ITEMS IN MANT < This was bothering me so much that its the reason I've tried to fix anything here tbh. The bot would sometimes go to the shop and not buy anything, which was a conglomerate of issues. Now the bot will go for the shop and scan the items correctly, then go back to the top and start its purchasing process. Then, it will compare the list of items that it planned to buy and compares it to you inventory, and if it realizes that one or more items were not bought it will try again only once, then give up if this fails again. I've also made some changes to make sure the bot is not trying to purchase items that are already purchased, but it didn't seem to work yet.

- Bot getting confused when deciding between rest and training. I'm not really sure why, but I think it had to do with the changes due to the addition of the sirius team card. The bot scored trainings and decided to rest, but since there was no recreation option it resets and goes back to weighting the options, which created tis infinite loop. This is 100% fixed now.

Overall the bot is a little slower due to the shop logic, but after a few MANT runs I can say it works perfectly now. I'm a very new beginner at this so this all may suck, but hey its working and I'm happy with it!

---

## Changelog

April 4th: 

Done like 3 mant runs with no issues so far, the bot is now more robust then ever.

- Made changes to how the bot handles infinite loops, so it now has a loop protection if it detects one. However, there should be less of these as I think that the logic that made it go into loop was fixed. Before it would get stuck into a REST > TRAIN decision loop when the trainings were not good or had a high failure rate and a scheduled race was detected. These were two different loops that triggered themselves so now the bot should: Prioritize scheduled G1 races at all costs, except if it has 0 energy. Then, if no G1 is detected, it will prioritize any G2 or G3 race, but take in consideration training and resting. If it decided the best course of action is resting, only then it will try to rest/recreate.

- Event handler being called infinitely: It seems this happened because the bot thought it made a decision already but it didn't, so now if the event text is still showing the bot will make a decision again just to make sure the event goes away. If it doesn't find an event in the database it will click the first option.

- Stuck in race menu: the bot will now lower the threshold to find a race (same as before) but now with the new race logic it won't go back to the main menu, preventing an infinite loop.

- Not buying items in shop: for some reason the bot was not buying items in the shop sometimes, even though it wanted to. So now, the bot makes his purchase list, goes through the shop looking for what to buy and then does it. If the planned item is not bought, it will go again (same as before) only once. The changes made are to make this more robust and less prone to failure, as the same item was being read as 2 different items when the bot was scrolling through the shop, but now it will try to ignore it as much as possible. The downside is that if two items are near each other (like, one after the other) it will count them as only 1.

- Energy item usage: the bot now uses other energy items to recover if there is a scheduled G1 and it has no energy, I'll just make it so it always race without energy at the end of year and during inspiration rounds in a future update

- Logs are now better: the logs didn't tell me shit before, so now it logs all its actions so I can see why it is acting like a lobotomized AI sometimes. Without this none of the fixes would've happened, not sure why I didn't start with this.
