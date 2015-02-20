// ==UserScript==
// @name         Learnit control panel
// @version      0.1
// @description  Various tools for improving learnit
// @author       Thomas Dybdahl Ahle
// @include      https://learnit.itu.dk/*
// ==/UserScript==

var panel = document.createElement("div");
panel.setAttribute('style', 'position: absolute; top:2px; left:25%; width:50%; background:white; text-align:center');
document.body.appendChild(panel);

// Force download
var button = document.createElement("button");
button.appendChild(document.createTextNode("Force downloads"));
button.addEventListener('click', function() {
    var as = document.querySelectorAll("a");
    for (var i = 0; i < as.length; i++) {
        if (as[i].hasAttribute('href')) {
            var href = as[i].getAttribute('href');
            as[i].setAttribute('href', href.replace(/forcedownload=1/, 'forcedownload=0'));
        }
    }
    console.log('done');
});
panel.appendChild(button);

// Hide Submitted button
var button = document.createElement("button");
button.appendChild(document.createTextNode("Hide submitted"));
button.addEventListener('click', function() {
    var trs = document.querySelectorAll("tr");
    for (var i = 0; i < trs.length; i++) {
        var div = trs[i].querySelector('.submissionstatussubmitted');
        if (div !== null)
            trs[i].style.display = 'none';
    }
    console.log('done');
});
panel.appendChild(button);

// Group sort
var button = document.createElement("button");
button.appendChild(document.createTextNode("Group sort"));
button.addEventListener('click', function() {
    var tbody = document.querySelector("tbody");
    var trs = Array.prototype.slice.call(tbody.querySelectorAll("tr.unselectedrow"));
    tbody.innerHTML = '';
    trs.sort(function(tr1, tr2) {
        var s1 = tr1.querySelector('.c5')===null ? '' : tr1.querySelector('.c5').textContent;
        var s2 = tr2.querySelector('.c5')===null ? '' : tr2.querySelector('.c5').textContent;
        return s1.localeCompare(s2);
    });
    for (var i = 0; i < trs.length; i++) {
        tbody.appendChild(trs[i]);
    }
    console.log('done');
});
panel.appendChild(button);

// Fullscreen
var button = document.createElement("button");
button.appendChild(document.createTextNode("Fullscreen"));
button.addEventListener('click', function() {
    var form = document.querySelector(".quickgradingform");
    form.style.position = 'absolute';
    form.style.top = '0';
    form.style.left = '0';
    form.style['z-index'] = '100';
    console.log('done');
});
panel.appendChild(button);

console.log('Control panel loaded');

